"""
Karandash Checklist Bot - Database module
SQLite orqali barcha ma'lumotlarni saqlaydi: foydalanuvchilar, rollar,
cheklist shablonlari, va kunlik javoblar.
"""

import sqlite3
import calendar
from datetime import datetime, date, timedelta
from contextlib import contextmanager

DB_PATH = "data/karandash.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Bazani va jadvallarni yaratadi (birinchi marta ishga tushganda)."""
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT,
            approved INTEGER DEFAULT 0,
            approved_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            section TEXT NOT NULL,        -- 'ochilish' | 'yopilish' | 'haftalik' | 'oyoxiri'
            item_number TEXT NOT NULL,    -- '1', '15a', '19.1' kabi
            text TEXT NOT NULL,
            weekly_days TEXT,             -- masalan 'mon,thu' faqat haftalik bandlar uchun
            active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            allow_comment INTEGER DEFAULT 0  -- 1 bo'lsa, band uchun izoh yozish so'raladi
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            submission_date TEXT NOT NULL,   -- 'YYYY-MM-DD'
            done INTEGER DEFAULT 0,
            comment TEXT,                    -- ixtiyoriy izoh (masalan oprixodavaniya uchun)
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (item_id) REFERENCES checklist_items(id)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            summary_date TEXT NOT NULL,
            opening_time TEXT,
            closing_time TEXT,
            opening_done_count INTEGER DEFAULT 0,
            opening_total_count INTEGER DEFAULT 0,
            closing_done_count INTEGER DEFAULT 0,
            closing_total_count INTEGER DEFAULT 0,
            UNIQUE(user_id, summary_date),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        # ---------- BOSHLIQ SHAXSIY VAZIFALARI ----------
        c.execute("""
        CREATE TABLE IF NOT EXISTS boss_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            task_type TEXT NOT NULL,     -- 'daily' | 'weekly' | 'monthly' | 'once' | 'prayer'
            time_str TEXT,               -- 'HH:MM', vazifa bajarilishi kerak bo'lgan vaqt
            weekly_days TEXT,            -- 'mon,wed,fri' (faqat weekly uchun)
            monthly_day INTEGER,         -- 1-31 (faqat monthly uchun)
            prayer_name TEXT,            -- 'bomdod'|'peshin'|'asr'|'shom'|'xufton' (faqat prayer)
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS boss_task_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,      -- 'YYYY-MM-DD'
            done INTEGER DEFAULT 0,
            done_at TEXT,
            last_reminder_at TEXT,       -- oxirgi "qattiq" eslatma vaqti (HH:MM)
            UNIQUE(task_id, log_date),
            FOREIGN KEY (task_id) REFERENCES boss_tasks(id)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS prayer_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bomdod TEXT, peshin TEXT, asr TEXT, shom TEXT, xufton TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        # ---------- TIJORAT TAKLIFI FIRMALAR ----------
        c.execute("""
        CREATE TABLE IF NOT EXISTS tijorat_firmalar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomi TEXT NOT NULL,
            manzil TEXT,
            stir TEXT,
            hisob TEXT,
            bank TEXT,
            mfo TEXT,
            telefon TEXT,
            direktor TEXT,
            direktor_familiya TEXT,
            okonx TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)


# ---------- USERS ----------

def create_or_get_user(telegram_id: int, full_name: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = c.fetchone()
        if row:
            return dict(row)
        c.execute(
            "INSERT INTO users (telegram_id, full_name) VALUES (?, ?)",
            (telegram_id, full_name),
        )
        c.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return dict(c.fetchone())


def set_user_role(telegram_id: int, role: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET role = ?, approved = 0 WHERE telegram_id = ?",
            (role, telegram_id),
        )


def approve_user(telegram_id: int, admin_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET approved = 1, approved_by = ? WHERE telegram_id = ?",
            (admin_id, telegram_id),
        )


def get_user(telegram_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def list_users_by_role(role: str = None):
    with get_conn() as conn:
        if role:
            rows = conn.execute(
                "SELECT * FROM users WHERE role = ? AND approved = 1", (role,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users WHERE approved = 1"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------- CHECKLIST ITEMS ----------

def get_monthend_window(check_date: date):
    """Berilgan sana uchun, shu sana qaysi 'oy oxiri ko'rinish oynasi'ga
    tegishli ekanini aniqlaydi. Oyna: shu oy oxirgi kunidan navbatdagi
    oyning 3-sanasigacha. Agar check_date shu oyna ichida bo'lmasa, None
    qaytaradi. Aks holda, oynani identifikatsiya qiluvchi 'YYYY-MM' (asosiy
    oy, ya'ni oxirgi kuni bo'lgan oy) qaytaradi."""
    year, month = check_date.year, check_date.month
    last_day_this_month = calendar.monthrange(year, month)[1]

    # Holat A: check_date - shu oyning OXIRGI kuni
    if check_date.day == last_day_this_month:
        return f"{year}-{month:02d}"

    # Holat B: check_date - OLDINGI oyning oxirgi kunidan keyin,
    # joriy oyning 1-3 sanasi ichida (oldingi oyning oynasi davom etmoqda)
    if check_date.day <= 3:
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        return f"{prev_year}-{prev_month:02d}"

    return None


def is_monthend_item_done_for_window(user_id: int, item_id: int, window_key: str):
    """Berilgan 'oy oxiri' bandi, shu oyna (window_key, masalan '2026-06')
    davomida ALLAQACHON bajarilganmi (har qanday kunda)? Agar ha, band
    qolgan kunlarda endi ko'rsatilmaydi."""
    year, month = map(int, window_key.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    window_start = date(year, month, last_day)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    window_end = date(next_year, next_month, 3)

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT submission_date, done FROM submissions
               WHERE user_id = ? AND item_id = ?
                 AND submission_date >= ? AND submission_date <= ?""",
            (user_id, item_id, window_start.isoformat(), window_end.isoformat()),
        ).fetchall()
        return any(r["done"] for r in rows)


def add_checklist_item(role, section, item_number, text, weekly_days=None,
                        sort_order=0, allow_comment=0):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO checklist_items
               (role, section, item_number, text, weekly_days, sort_order, allow_comment)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (role, section, item_number, text, weekly_days, sort_order, allow_comment),
        )


def get_visible_monthend_items(role: str, user_id: int, check_date: date):
    """Berilgan kunda, shu foydalanuvchi uchun KO'RINISHI kerak bo'lgan
    'oyoxiri' bandlarini qaytaradi (hali bajarilmagan va oyna ichida)."""
    window_key = get_monthend_window(check_date)
    if not window_key:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM checklist_items
               WHERE role = ? AND section = 'oyoxiri' AND active = 1
               ORDER BY sort_order, id""",
            (role,),
        ).fetchall()
        items = [dict(r) for r in rows]

    visible = []
    for it in items:
        if not is_monthend_item_done_for_window(user_id, it["id"], window_key):
            visible.append(it)
    return visible


def get_checklist_items(role: str, section: str, today_weekday: str = None):
    """today_weekday: 'mon','tue',... - faqat bugun chiqishi kerak bo'lgan
    haftalik bandlarni filtrlash uchun."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM checklist_items
               WHERE role = ? AND section = ? AND active = 1
               ORDER BY sort_order, id""",
            (role, section),
        ).fetchall()
        items = [dict(r) for r in rows]
        if today_weekday:
            filtered = []
            for it in items:
                if it["weekly_days"]:
                    days = it["weekly_days"].split(",")
                    if today_weekday in days:
                        filtered.append(it)
                else:
                    filtered.append(it)
            return filtered
        return items


# ---------- SUBMISSIONS ----------

def save_submission(user_id: int, item_id: int, submission_date: str, done: bool,
                     comment: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO submissions (user_id, item_id, submission_date, done, comment)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, item_id, submission_date, 1 if done else 0, comment),
        )


def is_section_done_today(user_id: int, summary_date: str, section: str) -> bool:
    """Bugun shu bo'lim (ochilish/yopilish) allaqachon yakunlanganmi?"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE user_id=? AND summary_date=?",
            (user_id, summary_date),
        ).fetchone()
        if not row:
            return False
        row = dict(row)
        if section == "ochilish":
            return bool(row["opening_time"])
        else:
            return bool(row["closing_time"])


def get_period_item_stats(role: str, start_date: str, end_date: str):
    """Berilgan rol va sanalar oralig'ida, HAR XODIM uchun ALOHIDA,
    har bandning jami bajarilgan/bajarilmagan sonini qaytaradi.
    Natija: {user_id: {"full_name": ..., "items": {item_id: {"text":..,
    "item_number":.., "done":N, "not_done":N}}}}"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id as user_id, u.full_name,
                      ci.id as item_id, ci.item_number, ci.text,
                      s.done
               FROM submissions s
               JOIN users u ON u.id = s.user_id
               JOIN checklist_items ci ON ci.id = s.item_id
               WHERE u.role = ?
                 AND s.submission_date >= ? AND s.submission_date <= ?
               ORDER BY u.full_name, ci.sort_order, ci.id""",
            (role, start_date, end_date),
        ).fetchall()

        result = {}
        for r in rows:
            r = dict(r)
            uid = r["user_id"]
            if uid not in result:
                result[uid] = {"full_name": r["full_name"], "items": {}}
            items = result[uid]["items"]
            iid = r["item_id"]
            if iid not in items:
                items[iid] = {
                    "item_number": r["item_number"],
                    "text": r["text"],
                    "done": 0,
                    "not_done": 0,
                }
            if r["done"]:
                items[iid]["done"] += 1
            else:
                items[iid]["not_done"] += 1
        return result


def update_daily_summary(user_id, summary_date, section,
                          time_str=None, done_count=0, total_count=0):
    """section: 'ochilish' yoki 'yopilish'. Ikkisi alohida saqlanadi,
    bir-birini ustidan yozmaydi."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM daily_summary WHERE user_id=? AND summary_date=?",
            (user_id, summary_date),
        ).fetchone()

        if section == "ochilish":
            new_vals = dict(
                opening_time=time_str,
                opening_done_count=done_count,
                opening_total_count=total_count,
            )
        else:
            new_vals = dict(
                closing_time=time_str,
                closing_done_count=done_count,
                closing_total_count=total_count,
            )

        if existing:
            row = dict(existing)
            row.update(new_vals)
            conn.execute(
                """UPDATE daily_summary SET
                   opening_time=?, closing_time=?,
                   opening_done_count=?, opening_total_count=?,
                   closing_done_count=?, closing_total_count=?
                   WHERE user_id=? AND summary_date=?""",
                (row["opening_time"], row["closing_time"],
                 row["opening_done_count"], row["opening_total_count"],
                 row["closing_done_count"], row["closing_total_count"],
                 user_id, summary_date),
            )
        else:
            base = dict(
                opening_time=None, closing_time=None,
                opening_done_count=0, opening_total_count=0,
                closing_done_count=0, closing_total_count=0,
            )
            base.update(new_vals)
            conn.execute(
                """INSERT INTO daily_summary
                   (user_id, summary_date, opening_time, closing_time,
                    opening_done_count, opening_total_count,
                    closing_done_count, closing_total_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, summary_date, base["opening_time"], base["closing_time"],
                 base["opening_done_count"], base["opening_total_count"],
                 base["closing_done_count"], base["closing_total_count"]),
            )


def get_daily_report(report_date: str):
    """Berilgan kun uchun barcha xodimlarning hisobotini qaytaradi.
    Ochilish + yopilish bandlari QO'SHILGAN holda (jami) qaytariladi."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.full_name, u.role, ds.opening_time, ds.closing_time,
                      ds.opening_done_count, ds.opening_total_count,
                      ds.closing_done_count, ds.closing_total_count
               FROM daily_summary ds
               JOIN users u ON u.id = ds.user_id
               WHERE ds.summary_date = ?
               ORDER BY u.role, u.full_name""",
            (report_date,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["done_count"] = (d["opening_done_count"] or 0) + (d["closing_done_count"] or 0)
            d["total_count"] = (d["opening_total_count"] or 0) + (d["closing_total_count"] or 0)
            results.append(d)
        return results


def get_incomplete_items(user_id: int, report_date: str):
    """Berilgan kunda bajarilmagan (done=0) bandlar ro'yxati."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ci.item_number, ci.text
               FROM submissions s
               JOIN checklist_items ci ON ci.id = s.item_id
               WHERE s.user_id = ? AND s.submission_date = ? AND s.done = 0""",
            (user_id, report_date),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_items_with_status(user_id: int, report_date: str):
    """Berilgan kunda foydalanuvchi topshirgan BARCHA bandlar, holati bilan
    (done=1/0). Bajarilganlar avval, keyin bajarilmaganlar."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ci.item_number, ci.text, s.done, s.comment
               FROM submissions s
               JOIN checklist_items ci ON ci.id = s.item_id
               WHERE s.user_id = ? AND s.submission_date = ?
               ORDER BY s.done DESC, ci.sort_order, ci.id""",
            (user_id, report_date),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_users_for_section(role: str, summary_date: str, section: str):
    """Berilgan rol uchun, bugun shu bo'limni (ochilish/yopilish) HALI
    yakunlamagan, tasdiqlangan foydalanuvchilar ro'yxati."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE role = ? AND approved = 1", (role,)
        ).fetchall()
        users = [dict(r) for r in rows]
        pending = []
        for u in users:
            if not is_section_done_today(u["id"], summary_date, section):
                pending.append(u)
        return pending


def force_finalize_section(user_id: int, summary_date: str, section: str, role: str):
    """Foydalanuvchi vaqtida yakunlamagan bo'lsa, BARCHA shu bo'lim bandlarini
    'bajarilmadi' deb belgilab, daily_summary'ni yopadi. Foydalanuvchi
    sessiyasida (context.user_data) qisman belgilagan bandlari bo'lsa, ular
    bu funksiya orqali hisobga olinmaydi — bot.py darajasida sessiya holati
    bo'lsa, undan foydalanish kerak; aks holda hammasi bajarilmagan hisoblanadi."""
    weekday_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    dt = datetime.strptime(summary_date, "%Y-%m-%d")
    weekday = weekday_map[dt.weekday()]
    items = get_checklist_items(role, section, today_weekday=weekday)

    for item in items:
        save_submission(user_id, item["id"], summary_date, False)

    time_str = datetime.now().strftime("%H:%M") + " (avtomatik)"
    update_daily_summary(
        user_id, summary_date, section,
        time_str=time_str, done_count=0, total_count=len(items),
    )


def force_finalize_section_with_marks(user_id: int, summary_date: str, section: str,
                                       role: str, marks: dict):
    """force_finalize_section bilan bir xil, lekin sessiyada foydalanuvchi
    allaqachon belgilagan (marks: {item_id: bool}) bandlarni hisobga oladi —
    faqat belgilanmaganlari 'bajarilmadi' deb yoziladi."""
    weekday_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    dt = datetime.strptime(summary_date, "%Y-%m-%d")
    weekday = weekday_map[dt.weekday()]
    items = get_checklist_items(role, section, today_weekday=weekday)

    done_count = 0
    for item in items:
        done = bool(marks.get(item["id"], False))
        save_submission(user_id, item["id"], summary_date, done)
        if done:
            done_count += 1

    time_str = datetime.now().strftime("%H:%M") + " (avtomatik)"
    update_daily_summary(
        user_id, summary_date, section,
        time_str=time_str, done_count=done_count, total_count=len(items),
    )


# =====================================================================
# BOSHLIQ SHAXSIY VAZIFALARI (boss_tasks)
# =====================================================================

PRAYER_ORDER = ["bomdod", "peshin", "asr", "shom", "xufton"]
PRAYER_LABELS = {
    "bomdod": "Bomdod", "peshin": "Peshin", "asr": "Asr",
    "shom": "Shom", "xufton": "Xufton",
}

PRAYER_HADITHS = [
    ('Rasululloh \u0631\ufdfa dedilar:\n"Kishi bilan kufr va shirk o\'rtasidagi '
     'narsa namozni tark qilishdir."', "Sahih Muslim"),
    ('Rasululloh \u0631\ufdfa dedilar:\n"Biz bilan ular (kofirlar) o\'rtasidagi '
     'ahd namozdir. Kim uni tark qilsa, kufrga ketibdi."', "Jami' at-Tirmidhi"),
    ('Qiyomat kuni birinchi hisob qilinadigan amal:\n"Bandaning qiyomat kuni '
     'birinchi hisob qilinadigan amali namozdir. Agar namozi to\'g\'ri bo\'lsa, '
     'najot topadi va muvaffaqiyat qozonadi. Agar namozi buzilgan bo\'lsa, '
     'ziyon ko\'radi."', "Sunan at-Tirmidhi"),
    ('Do\'zax ahlining so\'zi (Qur\'ondan):\n"Sizlarni Saqar (do\'zax)ga nima '
     'kiritdi?"\nUlar aytadilar:\n"Biz namoz o\'qiydiganlardan emas edik."',
     "Qur'on"),
    ('"Kim asr namozini tark qilsa, uning amallari behuda bo\'ladi."',
     "Sahih al-Bukhari"),
]

PRAYER_CLOSING_NOTE = (
    "Shu bilan birga, inson tirik ekan, tavba eshigi ochiq. Agar kimdir "
    "namozni tashlab qo'ygan bo'lsa, bugundan boshlasa, Allohning rahmati "
    "juda keng. Rasululloh \u0631\ufdfa:\n"
    '"Tavba qilgan kishi gunoh qilmagandek bo\'ladi."\n'
    "— Sunan Ibn Majah"
)


def add_boss_task(user_id, text, task_type, time_str=None, weekly_days=None,
                   monthly_day=None, prayer_name=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO boss_tasks
               (user_id, text, task_type, time_str, weekly_days, monthly_day, prayer_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, text, task_type, time_str, weekly_days, monthly_day, prayer_name),
        )
        return cur.lastrowid


def get_boss_tasks(user_id, active_only=True):
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM boss_tasks WHERE user_id = ? AND active = 1 ORDER BY time_str",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM boss_tasks WHERE user_id = ? ORDER BY time_str",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def deactivate_boss_task(task_id):
    with get_conn() as conn:
        conn.execute("UPDATE boss_tasks SET active = 0 WHERE id = ?", (task_id,))


def get_tasks_for_today(user_id, check_date: date):
    """Berilgan kunda BAJARILISHI kerak bo'lgan barcha vazifalarni qaytaradi
    (turi qaysi bo'lishidan qat'iy nazar — daily/weekly/monthly/once/prayer)."""
    weekday_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
    weekday = weekday_map[check_date.weekday()]
    all_tasks = get_boss_tasks(user_id)

    result = []
    for t in all_tasks:
        if t["task_type"] == "daily":
            result.append(t)
        elif t["task_type"] == "weekly":
            days = (t["weekly_days"] or "").split(",")
            if weekday in days:
                result.append(t)
        elif t["task_type"] == "monthly":
            if t["monthly_day"] == check_date.day:
                result.append(t)
        elif t["task_type"] == "once":
            result.append(t)
        elif t["task_type"] == "prayer":
            result.append(t)
    return result


def is_boss_task_done(task_id, log_date):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT done FROM boss_task_log WHERE task_id = ? AND log_date = ?",
            (task_id, log_date),
        ).fetchone()
        return bool(row and row["done"])


def mark_boss_task_done(task_id, log_date):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM boss_task_log WHERE task_id = ? AND log_date = ?",
            (task_id, log_date),
        ).fetchone()
        now_str = datetime.now().strftime("%H:%M")
        if existing:
            conn.execute(
                "UPDATE boss_task_log SET done = 1, done_at = ? "
                "WHERE task_id = ? AND log_date = ?",
                (now_str, task_id, log_date),
            )
        else:
            conn.execute(
                "INSERT INTO boss_task_log (task_id, log_date, done, done_at) "
                "VALUES (?, ?, 1, ?)",
                (task_id, log_date, now_str),
            )
    # 'once' turidagi vazifa bajarilgach, butunlay o'chiriladi (ro'yxatdan chiqadi)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT task_type FROM boss_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row and row["task_type"] == "once":
            conn.execute("UPDATE boss_tasks SET active = 0 WHERE id = ?", (task_id,))


def mark_boss_task_not_done(task_id, log_date):
    """Vazifani 'bajarilmadi' deb belgilaydi (✅ ni bekor qilish uchun ham
    ishlatiladi — toggle qaytarilishi mumkin)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM boss_task_log WHERE task_id = ? AND log_date = ?",
            (task_id, log_date),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE boss_task_log SET done = 0, done_at = NULL "
                "WHERE task_id = ? AND log_date = ?",
                (task_id, log_date),
            )
        else:
            conn.execute(
                "INSERT INTO boss_task_log (task_id, log_date, done) VALUES (?, ?, 0)",
                (task_id, log_date),
            )


def get_boss_task_by_id(task_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM boss_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None


def update_last_reminder(task_id, log_date, time_str):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM boss_task_log WHERE task_id = ? AND log_date = ?",
            (task_id, log_date),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE boss_task_log SET last_reminder_at = ? "
                "WHERE task_id = ? AND log_date = ?",
                (time_str, task_id, log_date),
            )
        else:
            conn.execute(
                "INSERT INTO boss_task_log (task_id, log_date, done, last_reminder_at) "
                "VALUES (?, ?, 0, ?)",
                (task_id, log_date, time_str),
            )


def get_last_reminder(task_id, log_date):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_reminder_at FROM boss_task_log WHERE task_id = ? AND log_date = ?",
            (task_id, log_date),
        ).fetchone()
        return row["last_reminder_at"] if row else None


def get_boss_daily_report(user_id, log_date):
    """Berilgan kunda, boshliqning barcha vazifalari va ularning holati."""
    tasks = get_tasks_for_today(user_id, datetime.strptime(log_date, "%Y-%m-%d").date())
    result = []
    for t in tasks:
        done = is_boss_task_done(t["id"], log_date)
        result.append({**t, "done": done})
    return result


# ---------- NAMOZ VAQTLARI ----------

def set_prayer_times(user_id, bomdod, peshin, asr, shom, xufton):
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM prayer_times WHERE user_id = ?", (user_id,)
        ).fetchone()
        now_str = datetime.now().isoformat()
        if existing:
            conn.execute(
                """UPDATE prayer_times SET bomdod=?, peshin=?, asr=?, shom=?,
                   xufton=?, updated_at=? WHERE user_id=?""",
                (bomdod, peshin, asr, shom, xufton, now_str, user_id),
            )
        else:
            conn.execute(
                """INSERT INTO prayer_times
                   (user_id, bomdod, peshin, asr, shom, xufton, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, bomdod, peshin, asr, shom, xufton, now_str),
            )


def get_prayer_times(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM prayer_times WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def ensure_prayer_tasks(user_id):
    """Foydalanuvchida 5 vaqt namoz uchun boss_tasks yozuvi yo'q bo'lsa,
    yaratadi (vaqtsiz — vaqt prayer_times jadvalidan olinadi)."""
    existing = get_boss_tasks(user_id)
    existing_prayers = {t["prayer_name"] for t in existing if t["task_type"] == "prayer"}
    for p in PRAYER_ORDER:
        if p not in existing_prayers:
            add_boss_task(user_id, PRAYER_LABELS[p], "prayer", prayer_name=p)


# =====================================================================
# TIJORAT TAKLIFI — FIRMALAR
# =====================================================================

def add_firma(nomi, manzil="", stir="", hisob="", bank="", mfo="",
              telefon="", direktor="", direktor_familiya="", okonx=""):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tijorat_firmalar
               (nomi, manzil, stir, hisob, bank, mfo, telefon,
                direktor, direktor_familiya, okonx)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (nomi, manzil, stir, hisob, bank, mfo, telefon,
             direktor, direktor_familiya, okonx),
        )
        return cur.lastrowid


def get_all_firmalar():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tijorat_firmalar WHERE active=1 ORDER BY nomi"
        ).fetchall()
        return [dict(r) for r in rows]


def get_firma(firma_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tijorat_firmalar WHERE id=?", (firma_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_firma(firma_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE tijorat_firmalar SET active=0 WHERE id=?", (firma_id,)
        )

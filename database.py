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

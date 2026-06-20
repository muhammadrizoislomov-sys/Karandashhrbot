"""
Karandash Checklist Bot - asosiy fayl
Ishga tushirish: python bot.py

Talab qilinadigan kutubxona: pip install python-telegram-bot==21.* python-dotenv
"""

import os
import logging
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters,
)

import database as db
import pdf_report

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = os.getenv("ADMIN_GROUP_ID")  # admin guruhining chat_id si

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

ROLES = {
    "sotuvchi": "🛒 Sotuvchi",
    "boshqaruvchi": "👔 Do'kon boshqaruvchisi",
    "b2b_menejer": "📋 B2B menejer",
    "broker": "🤝 Broker",
}

WEEKDAY_MAP = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun",
}

# Conversation holatlari
ASK_NAME, ASK_ROLE = range(2)

# Foydalanuvchi sessiyasida joriy cheklist holati
# user_data ichida saqlanadi: {'items': [...], 'index': 0, 'section': 'ochilish', 'answers': {}}


# ---------------- RO'YXATDAN O'TISH ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if user and user["role"] and user["approved"]:
        await update.message.reply_text(
            f"Salom, {user['full_name']}! Siz allaqachon ro'yxatdan o'tgansiz "
            f"({ROLES.get(user['role'], user['role'])}).\n\n"
            "Buyruqlar: /ochilish /yopilish /holat"
        )
        return ConversationHandler.END

    if user and user["role"] and not user["approved"]:
        await update.message.reply_text(
            "Sizning so'rovingiz hali admin tomonidan tasdiqlanmagan. "
            "Iltimos, kuting."
        )
        return ConversationHandler.END

    await update.message.reply_text("Assalomu alaykum! Ismingiz va familiyangizni kiriting:")
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text.strip()
    context.user_data["full_name"] = full_name
    db.create_or_get_user(update.effective_user.id, full_name)

    keyboard = [[InlineKeyboardButton(label, callback_data=f"role:{key}")]
                for key, label in ROLES.items()]
    await update.message.reply_text(
        "Rolingizni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_ROLE


async def role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role_key = query.data.split(":")[1]
    telegram_id = update.effective_user.id

    db.set_user_role(telegram_id, role_key)
    full_name = context.user_data.get("full_name", "Noma'lum")

    await query.edit_message_text(
        f"So'rovingiz adminga yuborildi: {ROLES[role_key]} sifatida.\n"
        "Tasdiqlanishini kuting."
    )

    if ADMIN_GROUP_ID:
        approve_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Tasdiqlash",
                                  callback_data=f"approve:{telegram_id}"),
            InlineKeyboardButton("❌ Rad etish",
                                  callback_data=f"reject:{telegram_id}"),
        ]])
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=f"🆕 {full_name} — {ROLES[role_key]} sifatida ro'yxatdan "
                 f"o'tmoqchi. Tasdiqlaysizmi?",
            reply_markup=approve_kb,
        )
    return ConversationHandler.END


async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, telegram_id = query.data.split(":")
    telegram_id = int(telegram_id)
    admin_id = update.effective_user.id

    if action == "approve":
        db.approve_user(telegram_id, admin_id)
        await query.edit_message_text(query.message.text + "\n\n✅ Tasdiqlandi.")
        await context.bot.send_message(
            chat_id=telegram_id,
            text="Tabriklaymiz! Sizning rolingiz tasdiqlandi. "
                 "Endi /ochilish va /yopilish buyruqlaridan foydalanishingiz mumkin.",
        )
    else:
        await query.edit_message_text(query.message.text + "\n\n❌ Rad etildi.")
        await context.bot.send_message(
            chat_id=telegram_id,
            text="Afsuski, so'rovingiz rad etildi. Admin bilan bog'laning.",
        )


# ---------------- RUXSAT TEKSHIRISH ----------------

def require_approved_user(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user or not user["role"]:
            await update.message.reply_text("Avval /start orqali ro'yxatdan o'ting.")
            return
        if not user["approved"]:
            await update.message.reply_text(
                "Sizning ro'yxatdan o'tishingiz hali tasdiqlanmagan."
            )
            return
        return await func(update, context, user)
    return wrapper


# ---------------- CHEKLIST OQIMI (oddiy format — sotuvchi va boshqalar) ----------------

def build_checklist_keyboard(items, marks):
    """Har bandga bitta tugma qator qiladi: [holat belgisi] band matni qisqartirilgan.
    Faqat 2 holat: ✅ (bajarildi) yoki ❌ (bajarilmadi) — neytral belgi yo'q."""
    rows = []
    for item in items:
        mark = "✅" if marks.get(item["id"]) else "❌"
        label = f"{mark} {item['item_number']}. {item['text']}"
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append([InlineKeyboardButton(label, callback_data=f"toggle:{item['id']}")])
    rows.append([InlineKeyboardButton("✅ Yakunlash", callback_data="finish")])
    return InlineKeyboardMarkup(rows)


def build_checklist_text(section, items, marks):
    done = sum(1 for it in items if marks.get(it["id"]))
    title = "Ochilish" if section == "ochilish" else "Yopilish"
    return (f"📋 {title} cheklisti — bajarilgan: {done}/{len(items)}\n\n"
            f"Har bandni bosib belgilang, so'ng \"✅ Yakunlash\" tugmasini bosing.")


# Rollar uchun "har band — alohida xabar" formati (tugma matn bilan
# cheklanmaydi, to'liq matn xabarning o'zida ko'rinadi)
PER_MESSAGE_ROLES = {"broker"}


async def start_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE, user, section=None):
    """section parametri /ochilish yoki /yopilish handlerlaridan beriladi."""
    today = date.today()
    weekday = WEEKDAY_MAP[today.weekday()]

    items = db.get_checklist_items(user["role"], section, today_weekday=weekday)

    # Broker uchun 'oyoxiri' bandlari yopilish bo'limiga avtomatik qo'shiladi
    if user["role"] == "broker" and section == "yopilish":
        monthend_items = db.get_visible_monthend_items(user["role"], user["id"], today)
        items = items + monthend_items

    if not items:
        await update.message.reply_text(
            f"Sizning rolingiz uchun '{section}' cheklisti hali tayyorlanmagan."
        )
        return

    context.user_data["checklist"] = {
        "section": section,
        "items": items,
        "marks": {},
        "comments": {},
        "user_db_id": user["id"],
        "started_at": datetime.now().strftime("%H:%M"),
    }

    if user["role"] in PER_MESSAGE_ROLES:
        context.user_data["checklist"]["index"] = 0
        await send_per_message_item(update, context)
    else:
        text = build_checklist_text(section, items, {})
        kb = build_checklist_keyboard(items, {})
        await update.message.reply_text(text, reply_markup=kb)


# ---------------- CHEKLIST OQIMI (per-message format — broker) ----------------

def build_per_item_keyboard(item):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅", callback_data=f"pm_done:{item['id']}"),
        InlineKeyboardButton("❌", callback_data=f"pm_notdone:{item['id']}"),
    ]])


async def send_per_message_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data["checklist"]
    idx = state["index"]
    items = state["items"]

    if idx >= len(items):
        await finish_checklist(update, context)
        return

    item = items[idx]
    text = f"[{idx + 1}/{len(items)}] {item['item_number']}-band:\n\n{item['text']}"
    kb = build_per_item_keyboard(item)

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def per_message_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    state = context.user_data.get("checklist")
    if not state:
        await query.answer("Sessiya tugagan. Qaytadan /ochilish yoki /yopilish bering.",
                            show_alert=True)
        return

    action, item_id_str = query.data.split(":")
    item_id = int(item_id_str)
    done = (action == "pm_done")
    state["marks"][item_id] = done

    items = state["items"]
    current_item = next((it for it in items if it["id"] == item_id), None)

    await query.answer()
    mark = "✅" if done else "❌"
    await query.edit_message_text(
        f"{mark} {current_item['item_number']}-band:\n\n{current_item['text']}"
    )

    # Agar band izoh yozishni talab qilsa (allow_comment=1)
    if current_item and current_item.get("allow_comment"):
        context.user_data["awaiting_comment_for"] = item_id
        await query.message.reply_text(
            "Iltimos, shu band bo'yicha izoh yozing (yo'q bo'lsa \"yo'q\" deb yozing):"
        )
        return  # Keyingi bandga o'tish izoh kelgandan keyin bo'ladi

    state["index"] += 1
    await send_per_message_item(update, context)


async def per_message_comment_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi izoh yozganda (allow_comment bandidan keyin) chaqiriladi."""
    item_id = context.user_data.get("awaiting_comment_for")
    state = context.user_data.get("checklist")
    if not item_id or not state:
        return  # Bu oddiy xabar, cheklistga aloqasi yo'q

    comment_text = update.message.text
    state["comments"][item_id] = comment_text
    context.user_data.pop("awaiting_comment_for", None)

    await update.message.reply_text("Izoh qabul qilindi.")
    state["index"] += 1
    await send_per_message_item(update, context)


async def checklist_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bitta bandning ✅/⬜ holatini almashtiradi, xabarni yangilaydi."""
    query = update.callback_query
    state = context.user_data.get("checklist")

    if not state:
        await query.answer("Sessiya tugagan. Qaytadan /ochilish yoki /yopilish bering.",
                            show_alert=True)
        return

    item_id = int(query.data.split(":")[1])
    marks = state["marks"]
    marks[item_id] = not marks.get(item_id, False)

    await query.answer()
    text = build_checklist_text(state["section"], state["items"], marks)
    kb = build_checklist_keyboard(state["items"], marks)
    await query.edit_message_text(text, reply_markup=kb)


async def checklist_finish_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    state = context.user_data.get("checklist")

    if not state:
        await query.answer("Sessiya tugagan.", show_alert=True)
        return

    await query.answer()
    await finish_checklist(update, context)


async def finish_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data["checklist"]
    today_str = date.today().isoformat()
    finished_at = datetime.now().strftime("%H:%M")
    user_db_id = state["user_db_id"]
    items = state["items"]
    marks = state["marks"]
    comments = state.get("comments", {})

    done_count = 0
    for item in items:
        done = bool(marks.get(item["id"], False))
        comment = comments.get(item["id"])
        db.save_submission(user_db_id, item["id"], today_str, done, comment=comment)
        if done:
            done_count += 1
    total_count = len(items)

    if state["section"] == "ochilish":
        db.update_daily_summary(
            user_db_id, today_str, "ochilish",
            time_str=state["started_at"],
            done_count=done_count, total_count=total_count,
        )
    else:
        db.update_daily_summary(
            user_db_id, today_str, "yopilish",
            time_str=finished_at,
            done_count=done_count, total_count=total_count,
        )

    text = (f"✅ {state['section'].capitalize()} cheklisti yakunlandi.\n"
            f"Bajarilgan: {done_count}/{total_count}\n"
            f"Vaqt: {finished_at}")

    await query_or_message_reply(update, text)

    if state["section"] == "yopilish":
        closing_msg = (
            "Bugungi ishingiz uchun rahmat! 🙏\n"
            "Yaxshi dam oling, ertaga ko'rishguncha! 👋"
        )
        if update.callback_query:
            await update.callback_query.message.reply_text(closing_msg)
        else:
            await update.message.reply_text(closing_msg)

    context.user_data.pop("checklist", None)


async def query_or_message_reply(update: Update, text: str):
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def cmd_ochilish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or not user["approved"]:
        await update.message.reply_text("Avval ro'yxatdan o'tib, tasdiqlanishingiz kerak.")
        return
    today_str = date.today().isoformat()
    if db.is_section_done_today(user["id"], today_str, "ochilish"):
        await update.message.reply_text(
            "Bugungi ochilish cheklisti allaqachon to'ldirilgan. "
            "Ertaga yana to'ldirishingiz mumkin."
        )
        return
    await start_checklist(update, context, user, section="ochilish")


async def cmd_yopilish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or not user["approved"]:
        await update.message.reply_text("Avval ro'yxatdan o'tib, tasdiqlanishingiz kerak.")
        return
    today_str = date.today().isoformat()
    if db.is_section_done_today(user["id"], today_str, "yopilish"):
        await update.message.reply_text(
            "Bugungi yopilish cheklisti allaqachon to'ldirilgan. "
            "Ertaga yana to'ldirishingiz mumkin."
        )
        return
    if not db.is_section_done_today(user["id"], today_str, "ochilish"):
        await update.message.reply_text(
            "Yopilish cheklistini boshlashdan oldin, avval ochilish "
            "cheklistini yakunlashingiz kerak (/ochilish)."
        )
        return
    await start_checklist(update, context, user, section="yopilish")


# ---------------- HOLAT ----------------

async def cmd_holat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_str = date.today().isoformat()
    rows = db.get_daily_report(today_str)
    if not rows:
        await update.message.reply_text("Bugun hali hech kim cheklist topshirmagan.")
        return

    lines = [f"📊 Bugungi holat — {today_str}\n"]
    for r in rows:
        op = r["opening_time"] or "—"
        cl = r["closing_time"] or "—"
        lines.append(
            f"{r['full_name']} ({ROLES.get(r['role'], r['role'])})\n"
            f"  Ochilish: {op} | Yopilish: {cl} | "
            f"Bajarilgan: {r['done_count']}/{r['total_count']}"
        )
    await update.message.reply_text("\n\n".join(lines))


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """VAQTINCHA buyruq — shu chatning ID sini ko'rsatadi.
    Guruh ID sini topib bo'lgach, bu funksiyani va pastdagi
    add_handler qatorini o'chirib tashlash mumkin."""
    await update.message.reply_text(
        f"Bu chatning ID si: {update.effective_chat.id}"
    )


async def is_admin_chat(update: Update) -> bool:
    """Faqat ADMIN_GROUP_ID dan yuborilgan buyruqlarga ruxsat beradi."""
    if not ADMIN_GROUP_ID:
        return False
    return str(update.effective_chat.id) == str(ADMIN_GROUP_ID)


def parse_report_date(args) -> str:
    """/hisobot 2026-06-18 yoki /hisobot (bugun) ni qabul qiladi."""
    if args and len(args) >= 1:
        try:
            datetime.strptime(args[0], "%Y-%m-%d")
            return args[0]
        except ValueError:
            pass
    return date.today().isoformat()


async def cmd_hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_chat(update):
        await update.message.reply_text(
            "Bu buyruq faqat admin guruhida ishlaydi."
        )
        return

    report_date = parse_report_date(context.args)
    await update.message.reply_text(f"📄 {report_date} uchun hisobot tayyorlanmoqda...")

    pdf_path = pdf_report.generate_daily_pdf(report_date)
    with open(pdf_path, "rb") as f:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=f,
            filename=f"hisobot_{report_date}.pdf",
            caption=f"Kunlik hisobot — {report_date}",
        )


def make_period_role_report_handler(role: str):
    """Har rol uchun /hisobot_<rol> buyrug'ini yaratadi.
    Foydalanish: /hisobot_sotuvchi 2026-06-15 2026-06-19"""
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await is_admin_chat(update):
            await update.message.reply_text(
                "Bu buyruq faqat admin guruhida ishlaydi."
            )
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "Foydalanish: /hisobot_" + role + " BOSHLANISH_SANA TUGASH_SANA\n"
                "Masalan: /hisobot_" + role + " 2026-06-15 2026-06-19"
            )
            return

        start_date, end_date = args[0], args[1]
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text(
                "Sana formati noto'g'ri. YYYY-MM-DD formatida yozing "
                "(masalan: 2026-06-15)."
            )
            return

        await update.message.reply_text(
            f"📄 {start_date} dan {end_date} gacha hisobot tayyorlanmoqda..."
        )
        pdf_path = pdf_report.generate_period_role_pdf(role, start_date, end_date)
        with open(pdf_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=f"hisobot_{role}_{start_date}_{end_date}.pdf",
                caption=f"Davriy hisobot — {ROLES.get(role, role)} "
                        f"({start_date} — {end_date})",
            )
    return handler


async def send_auto_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni ertalab 08:00da, KECHAGI kun uchun avtomatik PDF yuborish."""
    if not ADMIN_GROUP_ID:
        return
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    pdf_path = pdf_report.generate_daily_pdf(yesterday_str)
    with open(pdf_path, "rb") as f:
        await context.bot.send_document(
            chat_id=ADMIN_GROUP_ID,
            document=f,
            filename=f"hisobot_{yesterday_str}.pdf",
            caption=f"📄 Avtomatik kunlik hisobot — {yesterday_str}",
        )


def _get_session_marks(app: Application, telegram_id: int):
    """Foydalanuvchining hozir ochiq turgan cheklist sessiyasidagi
    belgilangan bandlarini (agar bor bo'lsa) qaytaradi: (section, marks) yoki
    (None, {}) agar sessiya yo'q bo'lsa."""
    user_data = app.user_data.get(telegram_id)
    if not user_data:
        return None, {}
    state = user_data.get("checklist")
    if not state:
        return None, {}
    return state.get("section"), state.get("marks", {})


async def send_morning_start_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 08:30da: ochilishni hali BOSHLAMAGAN (yakunlamagan)
    sotuvchi va brokerlarga, ishni boshlash haqida iliq eslatma."""
    today_str = date.today().isoformat()

    for role in ("sotuvchi", "broker"):
        pending = db.get_pending_users_for_section(role, today_str, "ochilish")
        for user in pending:
            try:
                await context.bot.send_message(
                    chat_id=user["telegram_id"],
                    text=("Assalomu alaykum! Kuningiz yaxshi boshlandimi? 🌅\n\n"
                          "Cheklistlarni boshlaylik endi — /ochilish tugmasini "
                          "bosing va ishni boshlang."),
                )
            except Exception as e:
                logger.warning(f"Ertalabki eslatma yuborilmadi "
                                f"({user['full_name']}): {e}")


async def send_seller_opening_warning(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 14:00da: ochilishni hali yakunlamagan sotuvchilarga,
    bajarilmagan bandlar ro'yxati bilan shaxsiy ogohlantirish."""
    today_str = date.today().isoformat()
    weekday = WEEKDAY_MAP[date.today().weekday()]
    pending = db.get_pending_users_for_section("sotuvchi", today_str, "ochilish")

    for user in pending:
        all_items = db.get_checklist_items("sotuvchi", "ochilish", today_weekday=weekday)
        _, marks = _get_session_marks(context.application, user["telegram_id"])
        not_done_texts = [
            it["text"] for it in all_items if not marks.get(it["id"], False)
        ]
        if not not_done_texts:
            continue
        lines = "\n".join(f"• {t}" for t in not_done_texts)
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=(f"⚠️ Diqqat! Quyidagi ochilish cheklisti bandlari hali "
                      f"bajarilmagan:\n\n{lines}\n\n"
                      f"Soat 15:00gacha yakunlashingiz kerak, aks holda "
                      f"avtomatik \"bajarilmagan\" deb belgilanadi."),
            )
        except Exception as e:
            logger.warning(f"Ogohlantirish yuborilmadi ({user['full_name']}): {e}")


async def auto_finalize_seller_opening(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 15:00da: ochilishni hali yakunlamagan sotuvchilar uchun,
    sessiyadagi belgilangan bandlarni hisobga olib, avtomatik yakunlash."""
    today_str = date.today().isoformat()
    pending = db.get_pending_users_for_section("sotuvchi", today_str, "ochilish")

    for user in pending:
        section, marks = _get_session_marks(context.application, user["telegram_id"])
        if section != "ochilish":
            marks = {}
        db.force_finalize_section_with_marks(
            user["id"], today_str, "ochilish", "sotuvchi", marks
        )
        app_user_data = context.application.user_data.get(user["telegram_id"])
        if app_user_data:
            app_user_data.pop("checklist", None)
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=("⏰ Vaqt tugadi. Ochilish cheklisti avtomatik yakunlandi. "
                      "Endi /yopilish cheklistini to'ldirishingiz mumkin."),
            )
        except Exception as e:
            logger.warning(f"Xabar yuborilmadi ({user['full_name']}): {e}")


async def auto_finalize_seller_closing(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 21:00da: yopilishni hali yakunlamagan sotuvchilar uchun
    avtomatik yakunlash."""
    today_str = date.today().isoformat()
    pending = db.get_pending_users_for_section("sotuvchi", today_str, "yopilish")

    for user in pending:
        section, marks = _get_session_marks(context.application, user["telegram_id"])
        if section != "yopilish":
            marks = {}
        db.force_finalize_section_with_marks(
            user["id"], today_str, "yopilish", "sotuvchi", marks
        )
        app_user_data = context.application.user_data.get(user["telegram_id"])
        if app_user_data:
            app_user_data.pop("checklist", None)
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text="⏰ Vaqt tugadi. Yopilish cheklisti avtomatik yakunlandi.",
            )
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=("Bugungi ishingiz uchun rahmat! 🙏\n"
                      "Yaxshi dam oling, ertaga ko'rishguncha! 👋"),
            )
        except Exception as e:
            logger.warning(f"Xabar yuborilmadi ({user['full_name']}): {e}")


async def send_previous_day_warning(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni ertalab (08:00, hisobot bilan bir vaqtda): kechagi kunda
    bajarilmagan bandlari bo'lgan sotuvchilarga shaxsiy ogohlantirish."""
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    sellers = db.list_users_by_role("sotuvchi")

    for user in sellers:
        incomplete = db.get_incomplete_items(user["id"], yesterday_str)
        if not incomplete:
            continue
        lines = "\n".join(f"• {it['text']}" for it in incomplete)
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=(f"📋 Sizda kecha ({yesterday_str}) bajarilmagan "
                      f"cheklist bandlari bor edi:\n\n{lines}\n\n"
                      f"Ishingizga mas'uliyat bilan yondashing."),
            )
        except Exception as e:
            logger.warning(f"Ogohlantirish yuborilmadi ({user['full_name']}): {e}")


# ---------------- ASOSIY ----------------

async def setup_bot_commands(app: Application):
    """Bot menyusiga (/ tugmasi) asosiy buyruqlarni qo'shadi."""
    await app.bot.set_my_commands([
        BotCommand("start", "Ro'yxatdan o'tish"),
        BotCommand("ochilish", "Kunlik ochilish cheklisti"),
        BotCommand("yopilish", "Kunlik yopilish cheklisti"),
        BotCommand("holat", "Bugungi holatni ko'rish"),
    ])


def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(setup_bot_commands).build()

    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_ROLE: [CallbackQueryHandler(role_chosen, pattern="^role:")],
        },
        fallbacks=[],
    )

    app.add_handler(reg_handler)
    app.add_handler(CallbackQueryHandler(admin_decision, pattern="^(approve|reject):"))
    app.add_handler(CommandHandler("ochilish", cmd_ochilish))
    app.add_handler(CommandHandler("yopilish", cmd_yopilish))
    app.add_handler(CommandHandler("holat", cmd_holat))
    app.add_handler(CommandHandler("chatid", cmd_chatid))  # VAQTINCHA
    app.add_handler(CommandHandler("hisobot", cmd_hisobot))
    for role_key in ROLES:
        app.add_handler(CommandHandler(
            f"hisobot_{role_key}", make_period_role_report_handler(role_key)
        ))
    app.add_handler(CallbackQueryHandler(checklist_toggle, pattern="^toggle:"))
    app.add_handler(CallbackQueryHandler(checklist_finish_button, pattern="^finish$"))
    app.add_handler(CallbackQueryHandler(per_message_answer, pattern="^pm_(done|notdone):"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, per_message_comment_received
    ))

    # Har kuni soat 08:00da, kechagi kun uchun avtomatik PDF hisobot
    if app.job_queue:
        app.job_queue.run_daily(
            send_auto_daily_report,
            time=datetime.strptime("08:00", "%H:%M").time(),
        )
        # Ertalab 08:05da, kechagi bajarilmagan bandlar haqida shaxsiy ogohlantirish
        app.job_queue.run_daily(
            send_previous_day_warning,
            time=datetime.strptime("08:05", "%H:%M").time(),
        )
        # 08:30da, ochilishni hali boshlamaganlarga (sotuvchi+broker) eslatma
        app.job_queue.run_daily(
            send_morning_start_reminder,
            time=datetime.strptime("08:30", "%H:%M").time(),
        )
        # 14:00da ochilish bo'yicha ogohlantirish (faqat sotuvchi)
        app.job_queue.run_daily(
            send_seller_opening_warning,
            time=datetime.strptime("14:00", "%H:%M").time(),
        )
        # 15:00da ochilishni avtomatik yakunlash (faqat sotuvchi)
        app.job_queue.run_daily(
            auto_finalize_seller_opening,
            time=datetime.strptime("15:00", "%H:%M").time(),
        )
        # 21:00da yopilishni avtomatik yakunlash (faqat sotuvchi)
        app.job_queue.run_daily(
            auto_finalize_seller_closing,
            time=datetime.strptime("21:00", "%H:%M").time(),
        )

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()

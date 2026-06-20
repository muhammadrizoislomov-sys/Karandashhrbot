"""
Karandash Checklist Bot - asosiy fayl
Ishga tushirish: python bot.py

Talab qilinadigan kutubxona: pip install python-telegram-bot==21.* python-dotenv
"""

import os
import logging
import random
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
(TASK_TEXT, TASK_TYPE, TASK_WEEKLY_DAYS, TASK_MONTHLY_DAY, TASK_TIME) = range(10, 15)
(PRAYER_BOMDOD, PRAYER_PESHIN, PRAYER_ASR, PRAYER_SHOM, PRAYER_XUFTON) = range(20, 25)

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
    """Foydalanuvchi izoh yozganda (allow_comment bandidan keyin) chaqiriladi.
    Agar izoh kutilmasa va bu admin guruhdan kelmagan oddiy xabar bo'lsa,
    xabarni admin guruhga forward qiladi (qo'llab-quvvatlash uchun)."""
    item_id = context.user_data.get("awaiting_comment_for")
    state = context.user_data.get("checklist")
    if item_id and state:
        comment_text = update.message.text
        state["comments"][item_id] = comment_text
        context.user_data.pop("awaiting_comment_for", None)

        await update.message.reply_text("Izoh qabul qilindi.")
        state["index"] += 1
        await send_per_message_item(update, context)
        return

    # Bu — cheklistga aloqasi yo'q, oddiy xabar.
    # Agar admin guruhdan kelmagan bo'lsa (ya'ni xodimdan), forward qilamiz.
    if not ADMIN_GROUP_ID or str(update.effective_chat.id) == str(ADMIN_GROUP_ID):
        return

    user = db.get_user(update.effective_user.id)
    if not user or not user["approved"]:
        return  # Ro'yxatdan o'tmagan/tasdiqlanmagan odamlardan xabar forward qilinmaydi

    role_label = ROLES.get(user["role"], user["role"])
    forwarded = await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=(f"✉️ {user['full_name']} ({role_label}):\n\n{update.message.text}"),
    )
    # Forward qilingan xabar ID sini, qaysi xodimga tegishli ekanini bilish
    # uchun saqlaymiz (admin shu xabarga Reply qilganda topish uchun)
    context.bot_data.setdefault("support_map", {})[forwarded.message_id] = (
        update.effective_user.id
    )


async def admin_reply_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin guruhda, forward qilingan xabarga Reply qilinganda, javobni
    tegishli xodimga yuboradi."""
    if not update.message.reply_to_message:
        return
    support_map = context.bot_data.get("support_map", {})
    original_id = update.message.reply_to_message.message_id
    target_telegram_id = support_map.get(original_id)
    if not target_telegram_id:
        return  # Bu forward qilingan support xabari emas

    try:
        await context.bot.send_message(
            chat_id=target_telegram_id,
            text=update.message.text,
        )
    except Exception as e:
        logger.warning(f"Admin javobi yuborilmadi: {e}")


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


# =====================================================================
# BOSHLIQ SHAXSIY VAZIFALARI MODULI
# =====================================================================

def require_boshqaruvchi(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = db.get_user(update.effective_user.id)
        if not user or user["role"] != "boshqaruvchi" or not user["approved"]:
            await update.message.reply_text(
                "Bu buyruq faqat tasdiqlangan Do'kon boshqaruvchisi uchun."
            )
            return ConversationHandler.END
        return await func(update, context, user)
    return wrapper


# ---------------- VAZIFA QO'SHISH OQIMI ----------------

@require_boshqaruvchi
async def cmd_vazifa_qosh(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    context.user_data["new_task"] = {"user_id": user["id"]}
    await update.message.reply_text("Yangi vazifa matnini yozing:")
    return TASK_TEXT


async def task_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_task"]["text"] = update.message.text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Har kuni", callback_data="ttype:daily")],
        [InlineKeyboardButton("📅 Har hafta", callback_data="ttype:weekly")],
        [InlineKeyboardButton("🗓️ Har oy", callback_data="ttype:monthly")],
        [InlineKeyboardButton("1️⃣ Bir martalik", callback_data="ttype:once")],
    ])
    await update.message.reply_text("Bu necha martalik vazifa?", reply_markup=kb)
    return TASK_TYPE


async def task_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ttype = query.data.split(":")[1]
    context.user_data["new_task"]["task_type"] = ttype

    if ttype == "weekly":
        await query.edit_message_text(
            "Qaysi kunlari? (masalan: mon,wed,fri — dushanba, chorshanba, juma)\n\n"
            "Kunlar: mon, tue, wed, thu, fri, sat, sun (vergul bilan ajratib yozing)"
        )
        return TASK_WEEKLY_DAYS
    elif ttype == "monthly":
        await query.edit_message_text("Oyning nechanchi kuni? (1-31 oralig'ida raqam yozing)")
        return TASK_MONTHLY_DAY
    else:
        await query.edit_message_text("Qaysi vaqtda eslatib turay? (masalan: 09:00)")
        return TASK_TIME


async def task_weekly_days_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days_raw = update.message.text.strip().lower()
    valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    days = [d.strip() for d in days_raw.split(",")]
    if not all(d in valid_days for d in days):
        await update.message.reply_text(
            "Noto'g'ri format. Masalan: mon,wed,fri — qaytadan yozing:"
        )
        return TASK_WEEKLY_DAYS
    context.user_data["new_task"]["weekly_days"] = ",".join(days)
    await update.message.reply_text("Qaysi vaqtda eslatib turay? (masalan: 15:00)")
    return TASK_TIME


async def task_monthly_day_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        day = int(update.message.text.strip())
        if not (1 <= day <= 31):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Iltimos, 1-31 oralig'ida raqam yozing:")
        return TASK_MONTHLY_DAY
    context.user_data["new_task"]["monthly_day"] = day
    await update.message.reply_text("Qaysi vaqtda eslatib turay? (masalan: 10:00)")
    return TASK_TIME


async def task_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_raw = update.message.text.strip()
    try:
        datetime.strptime(time_raw, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "Noto'g'ri format. Masalan: 09:00 — qaytadan yozing:"
        )
        return TASK_TIME

    data = context.user_data["new_task"]
    db.add_boss_task(
        data["user_id"], data["text"], data["task_type"],
        time_str=time_raw,
        weekly_days=data.get("weekly_days"),
        monthly_day=data.get("monthly_day"),
    )
    await update.message.reply_text(f"✅ Vazifa qo'shildi: \"{data['text']}\" — {time_raw}")
    context.user_data.pop("new_task", None)
    return ConversationHandler.END


# ---------------- VAZIFALARNI KO'RISH / O'CHIRISH ----------------

@require_boshqaruvchi
async def cmd_vazifalarim(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    today = date.today()
    tasks = db.get_tasks_for_today(user["id"], today)
    if not tasks:
        await update.message.reply_text(
            "Bugun uchun vazifalar yo'q. /vazifa_qosh orqali yangi vazifa qo'shing."
        )
        return

    text, kb = build_boss_tasklist_view(user["id"], today)
    await update.message.reply_text(text, reply_markup=kb)


@require_boshqaruvchi
async def cmd_vazifa_ochir(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    tasks = [t for t in db.get_boss_tasks(user["id"]) if t["task_type"] != "prayer"]
    if not tasks:
        await update.message.reply_text("O'chirish mumkin bo'lgan vazifa yo'q.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["text"][:50], callback_data=f"deltask:{t['id']}")]
        for t in tasks
    ])
    await update.message.reply_text("Qaysi vazifani o'chiramiz?", reply_markup=kb)


async def task_delete_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split(":")[1])
    db.deactivate_boss_task(task_id)
    await query.edit_message_text("✅ Vazifa o'chirildi.")


# ---------------- BAJARILDI / BAJARILMADI TUGMALARI ----------------

def build_boss_tasklist_view(user_id, check_date):
    """Berilgan kun uchun boshliq vazifalari matnini va tugmalarini quradi."""
    tasks = db.get_tasks_for_today(user_id, check_date)
    check_date_str = check_date.isoformat()

    lines = ["📋 Bugungi vazifalaringiz:\n"]
    buttons = []
    for t in tasks:
        done = db.is_boss_task_done(t["id"], check_date_str)
        time_part = f" ({t['time_str']})" if t["time_str"] else ""
        label = t["text"]
        if t["task_type"] == "prayer":
            pt = db.get_prayer_times(user_id)
            prayer_time = pt.get(t["prayer_name"]) if pt else None
            time_part = f" ({prayer_time})" if prayer_time else ""
            label = f"🕌 {t['text']}"

        status_icon = "✅" if done else "⬜"
        lines.append(f"{status_icon} {label}{time_part}")

        buttons.append([
            InlineKeyboardButton(
                f"✅ {label[:30]}", callback_data=f"bosstask_done:{t['id']}"
            ),
            InlineKeyboardButton(
                f"❌ {label[:30]}", callback_data=f"bosstask_notdone:{t['id']}"
            ),
        ])

    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(buttons) if buttons else None
    return text, kb


async def boss_task_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✅/❌ tugmalari bosilganda, vazifa holatini yangilaydi va BUTUN
    ro'yxatni qayta chizadi (boshqa vazifalar yo'qolib qolmasin)."""
    query = update.callback_query
    await query.answer()
    action, task_id_str = query.data.split(":")
    task_id = int(task_id_str)
    today = date.today()
    today_str = today.isoformat()

    if action == "bosstask_done":
        db.mark_boss_task_done(task_id, today_str)
    else:
        db.mark_boss_task_not_done(task_id, today_str)

    task = db.get_boss_task_by_id(task_id)
    text, kb = build_boss_tasklist_view(task["user_id"], today)
    await query.edit_message_text(text, reply_markup=kb)


async def boss_task_reminder_done_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Soatlik eslatma xabaridagi '✅ Bajarildi' tugmasi — faqat shu
    eslatma xabarini yangilaydi, ro'yxatni qayta chizmaydi."""
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split(":")[1])
    today_str = date.today().isoformat()
    db.mark_boss_task_done(task_id, today_str)
    await query.edit_message_text(query.message.text + "\n\n✅ Bajarildi deb belgilandi.")


# ---------------- JUMA KUNI NAMOZ VAQTLARINI SO'RASH ----------------

async def ask_friday_prayer_times(context: ContextTypes.DEFAULT_TYPE):
    """Har juma kuni, ertalab, boshqaruvchilardan yangi hafta uchun namoz
    vaqtlarini so'raydi."""
    bosses = db.list_users_by_role("boshqaruvchi")
    for user in bosses:
        context.application.user_data.setdefault(user["telegram_id"], {})[
            "prayer_update_user_id"] = user["id"]
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=("🕌 Yangi hafta uchun namoz vaqtlarini yangilaylik.\n\n"
                      "Bomdod namozi vaqtini kiriting (masalan 05:00):"),
            )
        except Exception as e:
            logger.warning(f"Namoz vaqti so'rovi yuborilmadi ({user['full_name']}): {e}")


@require_boshqaruvchi
async def cmd_namoz_vaqtlari(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    """Boshqaruvchi o'zi /namoz_vaqtlari buyrug'i bilan ham yangilashni boshlashi mumkin."""
    context.user_data["prayer_update_user_id"] = user["id"]
    await update.message.reply_text("Bomdod namozi vaqtini kiriting (masalan 05:00):")
    return PRAYER_BOMDOD


def _validate_time(text):
    try:
        datetime.strptime(text.strip(), "%H:%M")
        return text.strip()
    except ValueError:
        return None


async def prayer_bomdod_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = _validate_time(update.message.text)
    if not t:
        await update.message.reply_text("Noto'g'ri format (masalan 05:00). Qaytadan:")
        return PRAYER_BOMDOD
    context.user_data["prayer_times"] = {"bomdod": t}
    await update.message.reply_text("Peshin namozi vaqtini kiriting:")
    return PRAYER_PESHIN


async def prayer_peshin_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = _validate_time(update.message.text)
    if not t:
        await update.message.reply_text("Noto'g'ri format. Qaytadan:")
        return PRAYER_PESHIN
    context.user_data["prayer_times"]["peshin"] = t
    await update.message.reply_text("Asr namozi vaqtini kiriting:")
    return PRAYER_ASR


async def prayer_asr_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = _validate_time(update.message.text)
    if not t:
        await update.message.reply_text("Noto'g'ri format. Qaytadan:")
        return PRAYER_ASR
    context.user_data["prayer_times"]["asr"] = t
    await update.message.reply_text("Shom namozi vaqtini kiriting:")
    return PRAYER_SHOM


async def prayer_shom_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = _validate_time(update.message.text)
    if not t:
        await update.message.reply_text("Noto'g'ri format. Qaytadan:")
        return PRAYER_SHOM
    context.user_data["prayer_times"]["shom"] = t
    await update.message.reply_text("Xufton namozi vaqtini kiriting:")
    return PRAYER_XUFTON


async def prayer_xufton_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = _validate_time(update.message.text)
    if not t:
        await update.message.reply_text("Noto'g'ri format. Qaytadan:")
        return PRAYER_XUFTON

    pt = context.user_data["prayer_times"]
    user_id = context.user_data.get("prayer_update_user_id")
    db.set_prayer_times(user_id, pt["bomdod"], pt["peshin"], pt["asr"], pt["shom"], t)
    db.ensure_prayer_tasks(user_id)

    await update.message.reply_text(
        f"✅ Namoz vaqtlari yangilandi:\n"
        f"Bomdod: {pt['bomdod']} | Peshin: {pt['peshin']} | Asr: {pt['asr']} | "
        f"Shom: {pt['shom']} | Xufton: {t}"
    )
    context.user_data.pop("prayer_times", None)
    context.user_data.pop("prayer_update_user_id", None)
    return ConversationHandler.END


# ---------------- KUNLIK 08:00 RO'YXAT ----------------

async def send_boss_daily_tasklist(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 08:00da, boshqaruvchiga bugungi BARCHA vazifalarini
    bitta xabarda, bajarish tugmalari bilan yuboradi."""
    bosses = db.list_users_by_role("boshqaruvchi")
    today = date.today()

    for user in bosses:
        tasks = db.get_tasks_for_today(user["id"], today)
        if not tasks:
            continue

        text, kb = build_boss_tasklist_view(user["id"], today)
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"], text=text, reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"Kunlik vazifa ro'yxati yuborilmadi "
                            f"({user['full_name']}): {e}")


# ---------------- TEZKOR ESLATMALAR (vaqti o'tib, bajarilmagan) ----------------

async def check_boss_task_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Har 2 daqiqada ishga tushadi (09:00-23:00 oralig'ida). Vazifa vaqti
    o'tgan ZAHOTI birinchi eslatma yuboradi, keyin har soatda takrorlaydi."""
    now = datetime.now()
    if now.hour < 9 or now.hour >= 23:
        return

    today = date.today()
    today_str = today.isoformat()
    bosses = db.list_users_by_role("boshqaruvchi")

    for user in bosses:
        tasks = db.get_tasks_for_today(user["id"], today)
        for t in tasks:
            task_time_str = t["time_str"]
            if t["task_type"] == "prayer":
                pt = db.get_prayer_times(user["id"])
                task_time_str = pt.get(t["prayer_name"]) if pt else None
            if not task_time_str:
                continue

            try:
                task_time = datetime.strptime(task_time_str, "%H:%M").time()
            except ValueError:
                continue

            if now.time() < task_time:
                continue  # vaqti hali kelmagan

            if db.is_boss_task_done(t["id"], today_str):
                continue  # allaqachon bajarilgan

            last_reminder = db.get_last_reminder(t["id"], today_str)
            now_minutes_total = now.hour * 60 + now.minute

            if last_reminder:
                last_h, last_m = map(int, last_reminder.split(":"))
                last_minutes_total = last_h * 60 + last_m
                # Oxirgi eslatmadan kamida 60 daqiqa o'tmagan bo'lsa, kutamiz
                if now_minutes_total - last_minutes_total < 60:
                    continue

            current_time_str = now.strftime("%H:%M")
            db.update_last_reminder(t["id"], today_str, current_time_str)

            db.update_last_reminder(t["id"], today_str, current_hour_str)

            if t["task_type"] == "prayer":
                hadith_text, hadith_source = random.choice(db.PRAYER_HADITHS)
                text = (
                    f"🕌 {t['text']} namozi vaqti keldi, hali o'qimadingiz!\n\n"
                    f"{hadith_text}\n— {hadith_source}\n\n"
                    f"{db.PRAYER_CLOSING_NOTE}\n\n"
                    f"Namozingizni o'qing! 🤲"
                )
            else:
                text = (
                    f"⚠️ DIQQAT! \"{t['text']}\" vazifasi {task_time_str}da "
                    f"bajarilishi kerak edi, lekin hali bajarilmadi!\n\n"
                    f"Iltimos, darhol bajaring — vaqt isrof bo'lyapti!"
                )

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Bajarildi", callback_data=f"bosstask_remind:{t['id']}")
            ]])
            try:
                await context.bot.send_message(
                    chat_id=user["telegram_id"], text=text, reply_markup=kb,
                )
            except Exception as e:
                logger.warning(f"Eslatma yuborilmadi ({user['full_name']}): {e}")


# ---------------- 23:00 KUN YOPILISHI — SHAXSIY HISOBOT ----------------

async def send_boss_end_of_day_report(context: ContextTypes.DEFAULT_TYPE):
    """Har kuni 23:00da, boshqaruvchining o'ziga, bugungi bajarilgan/
    bajarilmagan vazifalari haqida shaxsiy hisobot yuboradi."""
    bosses = db.list_users_by_role("boshqaruvchi")
    today_str = date.today().isoformat()

    for user in bosses:
        report = db.get_boss_daily_report(user["id"], today_str)
        if not report:
            continue

        done_items = [r for r in report if r["done"]]
        not_done_items = [r for r in report if not r["done"]]

        lines = [f"📊 Bugungi hisobot — {today_str}\n"]
        lines.append(f"✅ Bajarilgan ({len(done_items)}):")
        for r in done_items:
            lines.append(f"  • {r['text']}")
        if not_done_items:
            lines.append(f"\n❌ Bajarilmagan ({len(not_done_items)}):")
            for r in not_done_items:
                lines.append(f"  • {r['text']}")

        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"], text="\n".join(lines),
            )
        except Exception as e:
            logger.warning(f"Kunlik hisobot yuborilmadi ({user['full_name']}): {e}")


# ---------------- ASOSIY ----------------

async def setup_bot_commands(app: Application):
    """Bot menyusiga (/ tugmasi) asosiy buyruqlarni qo'shadi."""
    await app.bot.set_my_commands([
        BotCommand("start", "Ro'yxatdan o'tish"),
        BotCommand("ochilish", "Kunlik ochilish cheklisti"),
        BotCommand("yopilish", "Kunlik yopilish cheklisti"),
        BotCommand("holat", "Bugungi holatni ko'rish"),
        BotCommand("vazifa_qosh", "Yangi shaxsiy vazifa qo'shish (boshqaruvchi)"),
        BotCommand("vazifalarim", "Mening vazifalarim ro'yxati (boshqaruvchi)"),
        BotCommand("vazifa_ochir", "Vazifani o'chirish (boshqaruvchi)"),
        BotCommand("namoz_vaqtlari", "Namoz vaqtlarini yangilash (boshqaruvchi)"),
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

    task_add_handler = ConversationHandler(
        entry_points=[CommandHandler("vazifa_qosh", cmd_vazifa_qosh)],
        states={
            TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_text_received)],
            TASK_TYPE: [CallbackQueryHandler(task_type_chosen, pattern="^ttype:")],
            TASK_WEEKLY_DAYS: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, task_weekly_days_received
            )],
            TASK_MONTHLY_DAY: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, task_monthly_day_received
            )],
            TASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_time_received)],
        },
        fallbacks=[],
    )

    prayer_update_handler = ConversationHandler(
        entry_points=[CommandHandler("namoz_vaqtlari", cmd_namoz_vaqtlari)],
        states={
            PRAYER_BOMDOD: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, prayer_bomdod_received
            )],
            PRAYER_PESHIN: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, prayer_peshin_received
            )],
            PRAYER_ASR: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, prayer_asr_received
            )],
            PRAYER_SHOM: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, prayer_shom_received
            )],
            PRAYER_XUFTON: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, prayer_xufton_received
            )],
        },
        fallbacks=[],
    )

    app.add_handler(reg_handler)
    app.add_handler(task_add_handler)
    app.add_handler(prayer_update_handler)
    app.add_handler(CallbackQueryHandler(admin_decision, pattern="^(approve|reject):"))
    app.add_handler(CommandHandler("ochilish", cmd_ochilish))
    app.add_handler(CommandHandler("yopilish", cmd_yopilish))
    app.add_handler(CommandHandler("holat", cmd_holat))
    app.add_handler(CommandHandler("chatid", cmd_chatid))  # VAQTINCHA
    app.add_handler(CommandHandler("hisobot", cmd_hisobot))
    app.add_handler(CommandHandler("vazifalarim", cmd_vazifalarim))
    app.add_handler(CommandHandler("vazifa_ochir", cmd_vazifa_ochir))
    for role_key in ROLES:
        app.add_handler(CommandHandler(
            f"hisobot_{role_key}", make_period_role_report_handler(role_key)
        ))
    app.add_handler(CallbackQueryHandler(checklist_toggle, pattern="^toggle:"))
    app.add_handler(CallbackQueryHandler(checklist_finish_button, pattern="^finish$"))
    app.add_handler(CallbackQueryHandler(per_message_answer, pattern="^pm_(done|notdone):"))
    app.add_handler(CallbackQueryHandler(task_delete_chosen, pattern="^deltask:"))
    app.add_handler(CallbackQueryHandler(
        boss_task_status_button, pattern="^bosstask_(done|notdone):"
    ))
    app.add_handler(CallbackQueryHandler(
        boss_task_reminder_done_button, pattern="^bosstask_remind:"
    ))

    if ADMIN_GROUP_ID:
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND
            & filters.Chat(chat_id=int(ADMIN_GROUP_ID))
            & filters.REPLY,
            admin_reply_received,
        ))
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

        # ---- Boshliq shaxsiy vazifalari ----
        # Har kuni 08:00da, bugungi vazifalar ro'yxati
        app.job_queue.run_daily(
            send_boss_daily_tasklist,
            time=datetime.strptime("08:00", "%H:%M").time(),
        )
        # Har 2 daqiqada tekshiradi (09:00dan boshlab), vazifa vaqti o'tgan
        # zahoti birinchi eslatma yuboradi, keyin har soatda takrorlaydi
        app.job_queue.run_repeating(
            check_boss_task_reminders,
            interval=120,  # 2 daqiqa
            first=datetime.strptime("09:00", "%H:%M").time(),
        )
        # 23:00da, kunlik shaxsiy hisobot
        app.job_queue.run_daily(
            send_boss_end_of_day_report,
            time=datetime.strptime("23:00", "%H:%M").time(),
        )
        # Har juma kuni ertalab 07:30da, namoz vaqtlarini yangilashni so'raydi
        app.job_queue.run_daily(
            ask_friday_prayer_times,
            time=datetime.strptime("07:30", "%H:%M").time(),
            days=(5,),  # PTB v20+: 0=yakshanba...6=shanba, demak juma=5
        )

    logger.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()

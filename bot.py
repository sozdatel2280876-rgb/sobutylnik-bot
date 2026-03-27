import asyncio
import html
import os
import random
from datetime import datetime, timezone

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

import db
try:
    from config import TOKEN as LOCAL_TOKEN
except Exception:
    LOCAL_TOKEN = None
try:
    from config import ADMIN_IDS as LOCAL_ADMIN_IDS
except Exception:
    LOCAL_ADMIN_IDS = []

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or LOCAL_TOKEN

if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN (or TOKEN) env var, or add TOKEN to config.py")


db.init_db()


def _parse_admin_ids() -> set[int]:
    ids = set()

    raw_admins = os.getenv("ADMIN_IDS", "")
    for item in raw_admins.split(","):
        candidate = item.strip()
        if candidate.isdigit():
            ids.add(int(candidate))

    source = LOCAL_ADMIN_IDS
    if isinstance(source, (str, int)):
        source = [source]

    if isinstance(source, (list, tuple, set)):
        for item in source:
            candidate = str(item).strip()
            if candidate.isdigit():
                ids.add(int(candidate))

    return ids


ADMIN_IDS = _parse_admin_ids()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


INACTIVE_LIKE_DAYS = _env_int("INACTIVE_LIKE_DAYS", 3)
REMINDER_COOLDOWN_HOURS = _env_int("REMINDER_COOLDOWN_HOURS", 24)
REMINDER_BATCH_SIZE = _env_int("REMINDER_BATCH_SIZE", 200)
FIRST_LIKE_BOOST_HOURS = _env_int("FIRST_LIKE_BOOST_HOURS", 24)
REFERRAL_BOOST_HOURS = _env_int("REFERRAL_BOOST_HOURS", 24)
PAID_BOOST_HOURS = _env_int("PAID_BOOST_HOURS", 24)
PAID_BOOST_PRICE_XTR = _env_int("PAID_BOOST_PRICE_XTR", 50)


def age_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["18", "19", "20"], ["21", "22", "23"], ["24", "25"], ["26+"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def city_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["Москва", "Санкт-Петербург"],
            ["Казань", "Новосибирск"],
            [KeyboardButton("📍 Отправить геолокацию", request_location=True)],
        ],
        resize_keyboard=True,
    )


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["🔥 Смотреть анкеты"], ["👤 Профиль", "💎 Буст 24ч"], ["🔁 Заполнить заново"]],
        resize_keyboard=True,
    )


def reminder_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👀 Показать анкеты", callback_data="show_profiles")]]
    )


def profile_link_html(user_id: int, display_name: str, username: str | None) -> str:
    if username:
        safe_username = html.escape(username)
        return f'<a href="https://t.me/{safe_username}">@{safe_username}</a>'

    safe_name = html.escape(display_name or "Пользователь")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def parse_referrer_from_args(args) -> int | None:
    if not args:
        return None

    token = (args[0] or "").strip()
    if token.startswith("ref_"):
        token = token[4:]

    if token.isdigit():
        return int(token)
    return None


async def get_referral_link(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str | None:
    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username

    if not username:
        return None
    return f"https://t.me/{username}?start=ref_{user_id}"


def is_boost_active_from_row(user_row) -> bool:
    if not user_row or len(user_row) < 10:
        return False

    boost_until = user_row[9]
    if not boost_until:
        return False

    if isinstance(boost_until, datetime):
        dt = boost_until
    else:
        raw = str(boost_until).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return False

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt > datetime.now(timezone.utc)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def ensure_not_banned(message, user_id: int) -> bool:
    if db.is_banned(user_id):
        await message.reply_text("Твой аккаунт заблокирован. Если это ошибка, напиши администратору.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id

    if not await ensure_not_banned(update.message, user_id):
        return

    existing_user = db.get_user(user_id)
    referrer_id = parse_referrer_from_args(context.args)

    if existing_user:
        referral_link = await get_referral_link(context, user_id)
        referrals_count = db.get_referrals_count(user_id)
        text = "С возвращением! Выбирай, что делаем дальше 👇"
        if referral_link:
            text += (
                "\n\nТвоя реферальная ссылка:\n"
                f"{referral_link}\n"
                f"Приглашено друзей: {referrals_count}"
            )
        await update.message.reply_text(text, reply_markup=main_menu())
        return

    context.user_data.clear()
    context.user_data["referrer_id"] = None

    if referrer_id and referrer_id != user_id and db.get_user(referrer_id):
        context.user_data["referrer_id"] = referrer_id

    context.user_data["step"] = "name"
    await update.message.reply_text(
        "Привет! Давай создадим анкету. Как тебя зовут?\n\n"
        "🎁 Бонус: за первый лайк ты получишь +24 часа буста анкеты.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await ensure_not_banned(update.message, update.effective_user.id):
        return

    text = (update.message.text or "").strip()
    step = context.user_data.get("step")

    if text == "🔁 Заполнить заново":
        await start(update, context)
        return

    if text == "👤 Профиль":
        await show_profile(update, context)
        return

    if text == "💎 Буст 24ч":
        await buy_boost(update, context)
        return

    if text == "🔥 Смотреть анкеты":
        await send_next_profile(update.message, context, update.effective_user.id)
        return

    if step == "name":
        if len(text) < 2:
            await update.message.reply_text("Введи имя чуть длиннее (минимум 2 символа).")
            return
        context.user_data["name"] = text
        context.user_data["step"] = "age"
        await update.message.reply_text("Сколько тебе лет?", reply_markup=age_keyboard())
        return

    if step == "age":
        if not text.replace("+", "").isdigit():
            await update.message.reply_text("Выбери возраст кнопкой ниже.")
            return
        context.user_data["age"] = text
        context.user_data["step"] = "city"
        await update.message.reply_text("Выбери город или отправь геолокацию.", reply_markup=city_keyboard())
        return

    if step == "city":
        context.user_data["city"] = text
        context.user_data["lat"] = None
        context.user_data["lon"] = None
        context.user_data["about"] = "Ищу компанию и новые знакомства 🍻"
        context.user_data["step"] = "photo"
        await update.message.reply_text("Отправь фото профиля 📸")
        return

    if step == "about":
        context.user_data["about"] = text
        context.user_data["step"] = "photo"
        await update.message.reply_text("Отправь фото профиля 📸")
        return

    if step == "photo":
        await update.message.reply_text("Нужно отправить именно фото, не текст 🙂")
        return

    await relay_to_matches(update, context)


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await ensure_not_banned(update.message, update.effective_user.id):
        return

    if context.user_data.get("step") != "city":
        return

    loc = update.message.location
    context.user_data["lat"] = loc.latitude
    context.user_data["lon"] = loc.longitude
    context.user_data["city"] = "Геолокация"
    context.user_data["about"] = "Ищу компанию и новые знакомства 🍻"
    context.user_data["step"] = "photo"

    await update.message.reply_text("Отлично, локацию получил. Отправь фото профиля 📸")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await ensure_not_banned(update.message, update.effective_user.id):
        return

    if context.user_data.get("step") != "photo":
        return

    photo = update.message.photo[-1].file_id

    required = ["name", "age", "city"]
    if not all(k in context.user_data for k in required):
        await update.message.reply_text("Что-то сбилось. Нажми /start и пройди регистрацию заново.")
        return

    about_text = context.user_data.get("about") or "Ищу компанию и новые знакомства 🍻"
    user_id = update.effective_user.id
    was_existing = db.get_user(user_id) is not None

    db.add_user(
        user_id,
        context.user_data["name"],
        context.user_data["age"],
        context.user_data["city"],
        about_text,
        photo,
        context.user_data.get("lat"),
        context.user_data.get("lon"),
    )

    if not was_existing:
        referrer_id = context.user_data.get("referrer_id")
        if referrer_id and referrer_id != user_id and db.add_referral(referrer_id, user_id):
            db.set_boost_hours(user_id, REFERRAL_BOOST_HOURS)
            db.set_boost_hours(referrer_id, REFERRAL_BOOST_HOURS)
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=(
                        "🎉 Друг зарегистрировался по твоей ссылке!\n"
                        f"Ты получил +{REFERRAL_BOOST_HOURS}ч буста анкеты."
                    ),
                )
            except Exception:
                pass
            await update.message.reply_text(
                f"🎁 Ты пришел по реферальной ссылке и получил +{REFERRAL_BOOST_HOURS}ч буста!"
            )

    context.user_data["step"] = None
    await update.message.reply_text("Анкета сохранена ✅", reply_markup=main_menu())

    referral_link = await get_referral_link(context, user_id)
    if referral_link:
        await update.message.reply_text(
            "🚀 Быстрый старт:\n"
            "1) Ставь лайки и получай мэтчи\n"
            "2) За первый лайк — бонус буст\n"
            "3) Приглашай друзей по ссылке:\n"
            f"{referral_link}"
        )

    await send_next_profile(update.message, context, update.effective_user.id)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("У тебя пока нет анкеты. Нажми /start.")
        return

    caption = f"🍻 {user[1]}, {user[2]}\n📍 {user[3]}\n\n{user[4]}"
    await update.message.reply_photo(user[5], caption=caption, reply_markup=main_menu())


async def send_boost_invoice(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if not db.get_user(user_id):
        await context.bot.send_message(chat_id=chat_id, text="Сначала создай анкету через /start")
        return

    payload = f"boost24:{user_id}:{int(datetime.now(timezone.utc).timestamp())}"
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=f"Буст анкеты +{PAID_BOOST_HOURS}ч",
        description="Приоритетный показ твоей анкеты в подборе.",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(f"Буст +{PAID_BOOST_HOURS}ч", PAID_BOOST_PRICE_XTR)],
        start_parameter="boost24",
    )


async def buy_boost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await ensure_not_banned(update.message, update.effective_user.id):
        return

    await send_boost_invoice(update.effective_chat.id, update.effective_user.id, context)


async def send_next_profile(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if not await ensure_not_banned(message, user_id):
        return

    me = db.get_user(user_id)
    if not me:
        await message.reply_text("Сначала создай анкету через /start")
        return

    await message.reply_text("🔍 Ищу анкеты...")
    await asyncio.sleep(0.8)

    users = db.get_search_candidates(user_id, like_cooldown_days=5, skip_cooldown_days=1)
    if not users:
        await message.reply_text("Пока никого нет. Попробуй позже.")
        return

    city = (me[3] or "").lower().strip()
    same_city = [u for u in users if (u[3] or "").lower().strip() == city]
    pool = same_city if same_city else users
    boosted_pool = [u for u in pool if is_boost_active_from_row(u)]
    target = random.choice(boosted_pool if boosted_pool else pool)

    context.user_data["target"] = target[0]

    text = f"🍻 {target[1]}, {target[2]}\n📍 {target[3]}\n\n{target[4]}"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👎", callback_data="skip"), InlineKeyboardButton("❤️", callback_data="like")],
            [InlineKeyboardButton("🚫 Жалоба", callback_data="report")],
        ]
    )

    await message.reply_photo(photo=target[5], caption=text, reply_markup=keyboard)


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if not await ensure_not_banned(query.message, user_id):
        return

    if query.data == "show_profiles":
        await send_next_profile(query.message, context, user_id)
        return

    target = context.user_data.get("target")
    if not target:
        await query.message.reply_text("Анкета не найдена, нажми '🔥 Смотреть анкеты'.")
        return

    if query.data == "like":
        is_new_like = not db.like_exists(user_id, target)
        db.add_like(user_id, target)

        if is_new_like and db.count_likes_given(user_id) == 1:
            if db.grant_reward_once(user_id, "first_like_bonus"):
                db.set_boost_hours(user_id, FIRST_LIKE_BOOST_HOURS)
                await query.message.reply_text(
                    f"🎁 Бонус за первый лайк: +{FIRST_LIKE_BOOST_HOURS}ч буста анкеты!"
                )

        if db.is_match(user_id, target):
            db.create_match(user_id, target)

            target_user = db.get_user(target)
            target_name = target_user[1] if target_user else "Пользователь"

            current_name = query.from_user.first_name or "Пользователь"
            current_username = query.from_user.username

            target_username = None
            try:
                target_chat = await context.bot.get_chat(target)
                target_username = target_chat.username
            except Exception:
                pass

            target_link = profile_link_html(target, target_name, target_username)
            current_link = profile_link_html(user_id, current_name, current_username)

            await query.message.reply_text(
                f"🔥 У вас мэтч!\nПиши сразу в личку: {target_link}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await context.bot.send_message(
                chat_id=target,
                text=f"🔥 У вас мэтч!\nПиши сразу в личку: {current_link}",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        elif is_new_like:
            try:
                await context.bot.send_message(
                    chat_id=target,
                    text="Тебе поставили лайк ❤️\nЗайди в бот и посмотри новые анкеты.",
                    reply_markup=main_menu(),
                )
            except Exception:
                pass
    elif query.data == "skip":
        db.add_skip(user_id, target)
    elif query.data == "report":
        db.add_report(user_id, target, "report_from_profile")
        db.add_skip(user_id, target)
        await query.message.reply_text("Жалоба отправлена. Эту анкету тебе больше не покажем.")

    await send_next_profile(query.message, context, user_id)


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if not query:
        return

    payload = query.invoice_payload or ""
    if query.currency != "XTR" or not payload.startswith("boost24:"):
        await query.answer(ok=False, error_message="Платеж отклонен. Попробуй еще раз.")
        return

    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.successful_payment:
        return

    payment = update.message.successful_payment
    payload = payment.invoice_payload or ""
    if not payload.startswith("boost24:"):
        return

    user_id = update.effective_user.id
    inserted = db.record_purchase(
        user_id=user_id,
        product_code="boost24",
        amount=int(payment.total_amount),
        currency=payment.currency,
        charge_id=payment.telegram_payment_charge_id,
    )

    if inserted:
        db.add_boost_hours(user_id, PAID_BOOST_HOURS)
        await update.message.reply_text(
            f"Оплата получена ✅\nТвой буст активирован на +{PAID_BOOST_HOURS}ч.",
            reply_markup=main_menu(),
        )
    else:
        await update.message.reply_text("Оплата уже обработана ✅", reply_markup=main_menu())


async def relay_to_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    matches = db.get_matches(user_id)
    if not matches:
        return

    await update.message.reply_text("После мэтча общайтесь в личке по ссылке, которую бот прислал.")


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Доступ запрещен.")
        return

    await update.message.reply_text(
        "Админ-команды:\n"
        "/stats — сводка по боту\n"
        "/reports — список открытых жалоб\n"
        "/ban <user_id> [причина] — заблокировать пользователя\n"
        "/unban <user_id> — снять блокировку\n"
        "/myid — показать твой Telegram ID"
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Доступ запрещен.")
        return

    stats = db.get_stats_snapshot()
    text = (
        "Статистика бота:\n"
        f"👥 Пользователей: {stats['users_total']}\n"
        f"⛔ В бане: {stats['banned_total']}\n"
        f"🚀 Активных бустов: {stats['boosts_active']}\n"
        f"🤝 Рефералов всего: {stats['referrals_total']}\n"
        f"💰 Покупок всего: {stats['purchases_total']}\n"
        f"⭐ Продано Stars: {stats['xtr_total']}\n"
        f"🚫 Открытых жалоб: {stats['open_reports_total']}\n"
        f"❤️ Лайков за 24ч: {stats['likes_24h']}\n"
        f"👎 Дизлайков за 24ч: {stats['skips_24h']}\n"
        f"📝 Жалоб за 24ч: {stats['reports_24h']}\n"
        f"🔥 Всего мэтчей: {stats['matches_total']}"
    )
    await update.message.reply_text(text)


async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Доступ запрещен.")
        return

    rows = db.get_open_reports(limit=20)
    if not rows:
        await update.message.reply_text("Открытых жалоб нет.")
        return

    lines = ["Открытые жалобы:"]
    for i, row in enumerate(rows, start=1):
        target_id = int(row[0])
        reports_count = int(row[1])
        user = db.get_user(target_id)
        name = user[1] if user else "Без анкеты"
        lines.append(f"{i}. {name} ({target_id}) — {reports_count} жалоб")

    lines.append("")
    lines.append("Команда: /ban <user_id> [причина]")
    await update.message.reply_text("\n".join(lines))


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text("Доступ запрещен.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /ban <user_id> [причина]")
        return

    target_id = int(context.args[0])
    if target_id == admin_id:
        await update.message.reply_text("Нельзя заблокировать самого себя.")
        return

    reason = " ".join(context.args[1:]).strip() or "Нарушение правил"
    db.ban_user(target_id, admin_id, reason)
    db.resolve_reports_for_user(target_id)

    await update.message.reply_text(f"Пользователь {target_id} заблокирован. Причина: {reason}")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"Твой аккаунт заблокирован. Причина: {reason}",
        )
    except Exception:
        pass


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Доступ запрещен.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Использование: /unban <user_id>")
        return

    target_id = int(context.args[0])
    db.unban_user(target_id)

    await update.message.reply_text(f"Пользователь {target_id} разблокирован.")
    try:
        await context.bot.send_message(chat_id=target_id, text="Твоя блокировка снята.")
    except Exception:
        pass


async def inactive_like_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_inactive_users_for_like_reminder(
        days=INACTIVE_LIKE_DAYS,
        remind_cooldown_hours=REMINDER_COOLDOWN_HOURS,
        limit=REMINDER_BATCH_SIZE,
    )

    for row in rows:
        user_id = int(row[0])
        try:
            user = db.get_user(user_id)
            name = "друг"
            if user and user[1]:
                name = user[1]

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"👋 {name}, давно тебя не было в подборе.\n"
                    "Нажми кнопку ниже и посмотри новые анкеты."
                ),
                reply_markup=reminder_inline_keyboard(),
            )
            db.mark_reminder_sent(user_id, "inactive_like")
        except Exception:
            pass


def run_webhook_if_configured(app) -> bool:
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL")
    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    if not webhook_base_url and render_host:
        webhook_base_url = f"https://{render_host}"

    if not webhook_base_url:
        return False

    webhook_path = os.getenv("WEBHOOK_PATH", "/telegram")
    if not webhook_path.startswith("/"):
        webhook_path = f"/{webhook_path}"

    webhook_url = f"{webhook_base_url.rstrip('/')}{webhook_path}"
    webhook_secret = os.getenv("WEBHOOK_SECRET") or None
    port = int(os.getenv("PORT", "10000"))

    print(f"Bot started in webhook mode: {webhook_url}")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=webhook_path.lstrip("/"),
        webhook_url=webhook_url,
        secret_token=webhook_secret,
        drop_pending_updates=True,
    )
    return True


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy_boost))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("reports", admin_reports))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    if app.job_queue:
        app.job_queue.run_repeating(
            inactive_like_reminder_job,
            interval=6 * 60 * 60,
            first=5 * 60,
            name="inactive_like_reminder",
        )
    else:
        print("Job queue is unavailable. Install APScheduler to enable reminders.")

    if run_webhook_if_configured(app):
        return

    print("Bot started in polling mode")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


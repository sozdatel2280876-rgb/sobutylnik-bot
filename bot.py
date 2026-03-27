import asyncio
import html
import os
import random

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
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
    filters,
)

import db
try:
    from config import TOKEN as LOCAL_TOKEN
except Exception:
    LOCAL_TOKEN = None

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or LOCAL_TOKEN

if not TOKEN:
    raise RuntimeError("Set BOT_TOKEN (or TOKEN) env var, or add TOKEN to config.py")


db.init_db()


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
        [["🔥 Смотреть анкеты"], ["👤 Профиль", "🔁 Заполнить заново"]],
        resize_keyboard=True,
    )


def profile_link_html(user_id: int, display_name: str, username: str | None) -> str:
    if username:
        safe_username = html.escape(username)
        return f'<a href="https://t.me/{safe_username}">@{safe_username}</a>'

    safe_name = html.escape(display_name or "Пользователь")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = "name"
    await update.message.reply_text(
        "Привет! Давай создадим анкету. Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove(),
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = (update.message.text or "").strip()
    step = context.user_data.get("step")

    if text == "🔁 Заполнить заново":
        await start(update, context)
        return

    if text == "👤 Профиль":
        await show_profile(update, context)
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
        context.user_data["step"] = "about"
        await update.message.reply_text("Коротко о себе?")
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

    if context.user_data.get("step") != "city":
        return

    loc = update.message.location
    context.user_data["lat"] = loc.latitude
    context.user_data["lon"] = loc.longitude
    context.user_data["city"] = "Геолокация"
    context.user_data["step"] = "about"

    await update.message.reply_text("Отлично, локацию получил. Коротко о себе?")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if context.user_data.get("step") != "photo":
        return

    photo = update.message.photo[-1].file_id

    required = ["name", "age", "city", "about"]
    if not all(k in context.user_data for k in required):
        await update.message.reply_text("Что-то сбилось. Нажми /start и пройди регистрацию заново.")
        return

    db.add_user(
        update.effective_user.id,
        context.user_data["name"],
        context.user_data["age"],
        context.user_data["city"],
        context.user_data["about"],
        photo,
        context.user_data.get("lat"),
        context.user_data.get("lon"),
    )

    context.user_data["step"] = None
    await update.message.reply_text("Анкета сохранена ✅", reply_markup=main_menu())
    await send_next_profile(update.message, context, update.effective_user.id)


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("У тебя пока нет анкеты. Нажми /start.")
        return

    caption = f"🍻 {user[1]}, {user[2]}\n📍 {user[3]}\n\n{user[4]}"
    await update.message.reply_photo(user[5], caption=caption, reply_markup=main_menu())


async def send_next_profile(message, context: ContextTypes.DEFAULT_TYPE, user_id: int):
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
    target = random.choice(same_city if same_city else users)

    context.user_data["target"] = target[0]

    text = f"🍻 {target[1]}, {target[2]}\n📍 {target[3]}\n\n{target[4]}"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("👎", callback_data="skip"), InlineKeyboardButton("❤️", callback_data="like")]]
    )

    await message.reply_photo(photo=target[5], caption=text, reply_markup=keyboard)


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    target = context.user_data.get("target")
    if not target:
        await query.message.reply_text("Анкета не найдена, нажми '🔥 Смотреть анкеты'.")
        return

    if query.data == "like":
        db.add_like(user_id, target)
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
    elif query.data == "skip":
        db.add_skip(user_id, target)

    await send_next_profile(query.message, context, user_id)


async def relay_to_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    matches = db.get_matches(user_id)
    if not matches:
        return

    await update.message.reply_text("После мэтча общайтесь в личке по ссылке, которую бот прислал.")


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
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    if run_webhook_if_configured(app):
        return

    print("Bot started in polling mode")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


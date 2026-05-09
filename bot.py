import logging
import os
from datetime import time
import pytz

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from database import Database
from tips import TipsLoader

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
ASK_WEEK = 0

# Timezone for daily sending (Kyiv)
KYIV_TZ = pytz.timezone("Europe/Kyiv")

db = Database()
tips = TipsLoader()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command — begin registration."""
    user_id = update.effective_user.id
    existing = db.get_user(user_id)

    if existing:
        await update.message.reply_text(
            "👶 Ти вже зареєстрована! Щодня о 9:00 тобі приходитиме порада.\n\n"
            "Якщо хочеш змінити термін — напиши /restart"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Привіт! 👋 Я твій помічник для вагітних 🤰\n\n"
        "Щодня я надсилатиму тобі корисні поради відповідно до твого терміну.\n\n"
        "На якому ти тижні вагітності? Напиши число від 1 до 40:"
    )
    return ASK_WEEK


async def receive_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive the pregnancy week from user."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Будь ласка, напиши число від 1 до 40 👇")
        return ASK_WEEK

    week = int(text)
    if week < 1 or week > 40:
        await update.message.reply_text("Термін має бути від 1 до 40 тижнів. Спробуй ще раз 👇")
        return ASK_WEEK

    user_id = update.effective_user.id
    # Convert week to day (start of that week)
    start_day = (week - 1) * 7 + 1
    db.save_user(user_id, start_day)

    await update.message.reply_text(
        f"✅ Чудово! Я запам'ятала, що ти на {week}-му тижні.\n\n"
        f"Щодня о 9:00 ранку тобі приходитиме порада 💛\n\n"
        f"Напиши /today щоб отримати сьогоднішню пораду прямо зараз!"
    )
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset user registration."""
    user_id = update.effective_user.id
    db.delete_user(user_id)
    await update.message.reply_text(
        "Починаємо спочатку! На якому ти тижні вагітності? Напиши число від 1 до 40:"
    )
    return ASK_WEEK


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send today's tip on demand."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        await update.message.reply_text(
            "Ти ще не зареєстрована! Напиши /start щоб розпочати 🌸"
        )
        return

    current_day = db.get_current_day(user_id)
    day_tips = tips.get_tips_for_day(current_day)

    if day_tips:
        await send_tips(update.message.chat_id, current_day, day_tips, context)
    else:
        await update.message.reply_text(
            f"На {current_day}-й день у мене немає порад, але я тут! 💛\n"
            "Завтра обов'язково буде щось корисне."
        )


async def send_tips(chat_id, day, day_tips, context):
    """Send tips to a specific chat."""
    week = (day - 1) // 7 + 1
    header = f"🌸 *День {day} | Тиждень {week}*\n\n"

    for tip in day_tips:
        text = header
        if tip.get("title"):
            text += f"*{tip['title']}*\n\n"
        text += tip["text"]

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown"
        )


async def send_daily_tips(context: ContextTypes.DEFAULT_TYPE):
    """Job: send daily tips to all users."""
    users = db.get_all_users()
    logger.info(f"Sending daily tips to {len(users)} users")

    for user in users:
        user_id = user["user_id"]
        current_day = db.get_current_day(user_id)

        if current_day > 280:
            logger.info(f"User {user_id} finished pregnancy (day {current_day})")
            continue

        day_tips = tips.get_tips_for_day(current_day)

        if day_tips:
            try:
                await send_tips(user_id, current_day, day_tips, context)
                logger.info(f"Sent tips for day {current_day} to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send to {user_id}: {e}")
        else:
            logger.info(f"No tips for day {current_day}, skipping user {user_id}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добре, до зустрічі! 👋")
    return ConversationHandler.END


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    # Load tips on startup
    tips.load()
    logger.info(f"Loaded tips for {len(tips.data)} days")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("restart", restart),
        ],
        states={
            ASK_WEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_week)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("today", today_command))

    # Schedule daily tips at 9:00 Kyiv time
    job_queue = app.job_queue
    job_queue.run_daily(
        send_daily_tips,
        time=time(hour=9, minute=0, tzinfo=KYIV_TZ),
        name="daily_tips"
    )

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

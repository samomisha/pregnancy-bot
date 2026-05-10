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
ASK_DAY = 0

# Timezone for daily sending (Kyiv)
KYIV_TZ = pytz.timezone("Europe/Kyiv")

# Admin user IDs
ADMIN_IDS = [260189699, 349776051]

db = Database()
tips = TipsLoader()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command — begin registration."""
    user_id = update.effective_user.id
    existing = db.get_user(user_id)

    if existing and existing.get("status") == "active":
        db.update_last_active(user_id)
        await update.message.reply_text(
            "👶 Ти вже зареєстрована! Щодня о 9:00 тобі приходитиме порада.\n\n"
            "Якщо хочеш змінити термін — напиши /restart\n"
            "Якщо хочеш відписатися — напиши /stop"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Привіт! 👋 Я твій помічник для вагітних 🤰\n\n"
        "Щодня я надсилатиму тобі корисні поради відповідно до твого терміну.\n\n"
        "На якому ти дні вагітності? Напиши число від 1 до 280:"
    )
    return ASK_DAY


async def receive_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive the pregnancy day from user."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Будь ласка, напиши число від 1 до 280 👇")
        return ASK_DAY

    day = int(text)
    if day < 1 or day > 280:
        await update.message.reply_text("Термін має бути від 1 до 280 днів. Спробуй ще раз 👇")
        return ASK_DAY

    user_id = update.effective_user.id
    db.save_user(user_id, day)

    week = (day - 1) // 7 + 1
    await update.message.reply_text(
        f"✅ Чудово! Я запам'ятала, що ти на {day}-му дні ({week}-й тиждень).\n\n"
        f"Щодня о 9:00 ранку тобі приходитиме порада 💛\n\n"
        f"Напиши /today щоб отримати сьогоднішню пораду прямо зараз!"
    )
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset user registration."""
    user_id = update.effective_user.id
    db.delete_user(user_id)
    await update.message.reply_text(
        "Починаємо спочатку! На якому ти дні вагітності? Напиши число від 1 до 280:"
    )
    return ASK_DAY


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send today's tip on demand."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user or user.get("status") != "active":
        await update.message.reply_text(
            "Ти ще не зареєстрована! Напиши /start щоб розпочати 🌸"
        )
        return

    db.update_last_active(user_id)
    current_day = db.get_current_day(user_id)
    day_tips = tips.get_tips_for_day(current_day)

    if day_tips:
        await send_tips(update.message.chat_id, current_day, day_tips, context)
    else:
        await update.message.reply_text(
            f"На {current_day}-й день у мене немає порад, але я тут! 💛\n"
            "Завтра обов'язково буде щось корисне."
        )


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show debug information: current day and all available days."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user or user.get("status") != "active":
        await update.message.reply_text(
            "Ти ще не зареєстрована! Напиши /start щоб розпочати 🌸"
        )
        return

    db.update_last_active(user_id)
    current_day = db.get_current_day(user_id)
    current_week = (current_day - 1) // 7 + 1
    
    # Get all days with tips
    available_days = sorted(tips.data.keys())
    
    # Format available days
    if available_days:
        days_str = ", ".join(str(day) for day in available_days)
        total_tips = sum(len(tips.data[day]) for day in available_days)
    else:
        days_str = "немає"
        total_tips = 0
    
    debug_info = (
        f"🔍 *Debug Information*\n\n"
        f"👤 User ID: `{user_id}`\n"
        f"📅 Поточний день: *{current_day}* (тиждень {current_week})\n"
        f"📊 Всього днів з порадами: *{len(available_days)}*\n"
        f"💡 Всього порад: *{total_tips}*\n\n"
        f"📋 Дні з порадами:\n`{days_str}`"
    )
    
    await update.message.reply_text(debug_info, parse_mode="Markdown")


async def send_tips(chat_id, day, day_tips, context):
    """Send tips to a specific chat."""
    week = (day - 1) // 7 + 1
    header = f"🌸 *День {day} | Тиждень {week}*\n\n"

    for tip in day_tips:
        text = header
        if tip.get("title"):
            text += f"*{tip['title']}*\n\n"
        text += tip["text"] + "\n"

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


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe from daily tips."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        await update.message.reply_text(
            "Ти не зареєстрована в боті."
        )
        return

    db.set_user_status(user_id, "inactive")
    db.update_last_active(user_id)
    
    await update.message.reply_text(
        "😔 Ти відписалася від щоденних порад.\n\n"
        "Якщо захочеш повернутися — просто напиши /start"
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    stats = db.get_stats()
    trimester_dist = db.get_trimester_distribution()
    
    stats_text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Всього користувачів: *{stats['total_users']}*\n"
        f"✅ Активних: *{stats['active_users']}*\n\n"
        f"📈 Нових за 7 днів: *{stats['new_7_days']}*\n"
        f"📈 Нових за 30 днів: *{stats['new_30_days']}*\n\n"
        f"📉 Відписок за 7 днів: *{stats['unsub_7_days']}*\n"
        f"📉 Відписок за 30 днів: *{stats['unsub_30_days']}*\n\n"
        f"🤰 *Розподіл по триместрах:*\n"
        f"1-й триместр (1-12 тижнів): *{trimester_dist[1]}*\n"
        f"2-й триместр (13-28 тижнів): *{trimester_dist[2]}*\n"
        f"3-й триместр (29-40 тижнів): *{trimester_dist[3]}*"
    )
    
    await update.message.reply_text(stats_text, parse_mode="Markdown")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show users list (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    users = db.get_all_users_with_details()
    
    if not users:
        await update.message.reply_text("Немає зареєстрованих користувачів.")
        return
    
    # Get user info from Telegram
    users_text = "👥 *Список користувачів:*\n\n"
    
    for user_data in users[:50]:  # Limit to 50 users per message
        user_id_val = user_data["user_id"]
        current_day = user_data["current_day"]
        current_week = user_data["current_week"]
        last_active = user_data["last_active"]
        status = user_data["status"]
        
        # Try to get user info
        try:
            chat = await context.bot.get_chat(user_id_val)
            username = chat.username if chat.username else "—"
            name = chat.first_name or "—"
        except:
            username = "—"
            name = "—"
        
        status_emoji = "✅" if status == "active" else "❌"
        last_active_str = last_active[:10] if last_active else "—"
        
        users_text += (
            f"{status_emoji} *{name}* (@{username})\n"
            f"   День {current_day} | Тиждень {current_week}\n"
            f"   Остання активність: {last_active_str}\n\n"
        )
    
    if len(users) > 50:
        users_text += f"\n_Показано перших 50 з {len(users)} користувачів_"
    
    await update.message.reply_text(users_text, parse_mode="Markdown")


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
            ASK_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("debug", debug_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("users", users_command))

    # Schedule tips every 2 hours for testing
    job_queue = app.job_queue
    job_queue.run_repeating(
        send_daily_tips,
        interval=7200,  # 2 hours in seconds
        first=10,  # Start after 10 seconds
        name="tips_every_2_hours"
    )

    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

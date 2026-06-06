import logging
import os
import asyncio
import html
from datetime import time, datetime, timedelta
import pytz
from aiohttp import web

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)

from database import Database
from tips import TipsLoader
import zenedu_webhook
import messages as msg
from datetime import date

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot version information
VERSION = "1.0.0"
LAST_UPDATE = "26.05.2026"
CHANGELOG = "перший реліз — реєстрація, розсилка порад, адмін-панель, Google Sheets, PostgreSQL"

# Bot start time for uptime tracking
bot_start_time = None

# Conversation states
ASK_DAY = 0
ASK_WEEK = 1
ADMIN_REPLY = 2
UNSUBSCRIBE_CONFIRM = 3

# Timezone for daily sending (Kyiv)
KYIV_TZ = pytz.timezone("Europe/Kyiv")

ADMIN_IDS = [260189699, 349776051]

# Store admin reply state: {admin_id: user_id}
admin_reply_to = {}

# Watchmode state: set of admin IDs with watchmode enabled
watchmode_admins = set()

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
        await log_user_action(context, user_id, "/start (вже зареєстрована)")
        return ConversationHandler.END

    # Show inline buttons for week or day selection
    keyboard = [
        [
            InlineKeyboardButton("📅 Ввести тиждень", callback_data="input_week"),
            InlineKeyboardButton("🗓 Ввести точний день", callback_data="input_day")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Привіт! 👋 Я твій помічник для вагітних 🤰\n\n"
        "Щодня я надсилатиму тобі корисні поради відповідно до твого терміну.\n\n"
        "Підкажи на якому ти етапі 🌸 Зазвичай достатньо вказати тиждень — але якщо знаєш точний день, можеш одразу його ввести!",
        reply_markup=reply_markup
    )
    await log_user_action(context, user_id, "/start (нова реєстрація)")
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
    
    # Set trial start for new users
    db.set_trial_start(user_id)

    week = (day - 1) // 7 + 1
    
    # Send today's tip + offer in one message
    current_day = db.get_current_day(user_id)
    day_tips = tips.get_tips_for_day(current_day)
    
    if day_tips:
        # Build combined message: tip + offer
        combined_text = f"🌸 *День {current_day} | Тиждень {week}*\n\n"
        
        # Add tip content
        for tip in day_tips:
            if tip.get("title"):
                combined_text += f"*{tip['title']}*\n\n"
            combined_text += tip["text"] + "\n\n"
        
        # Add offer text
        combined_text += msg.ONBOARDING_OFFER
        
        # Send combined message with button
        keyboard = [[InlineKeyboardButton(msg.ONBOARDING_BUTTON_TEXT, url=msg.ONBOARDING_BUTTON_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text=combined_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    return ConversationHandler.END


async def button_callback(query_update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks for week/day selection."""
    query = query_update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == "input_week":
        await query.edit_message_text(
            "📅 Чудово! Напиши номер тижня від 1 до 40:"
        )
        context.user_data["input_mode"] = "week"
        await log_user_action(context, user_id, "кнопка: 📅 Ввести тиждень")
        return ASK_WEEK
    elif query.data == "input_day":
        await query.edit_message_text(
            "🗓 Чудово! Напиши день вагітності від 1 до 280:"
        )
        context.user_data["input_mode"] = "day"
        await log_user_action(context, user_id, "кнопка: 🗓 Ввести точний день")
        return ASK_DAY


async def receive_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive the pregnancy week from user and convert to day."""
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Будь ласка, напиши число від 1 до 40 👇")
        return ASK_WEEK

    week = int(text)
    if week < 1 or week > 40:
        await update.message.reply_text("Тиждень має бути від 1 до 40. Спробуй ще раз 👇")
        return ASK_WEEK

    # Convert week to day (week * 7 - 6)
    day = week * 7 - 6
    user_id = update.effective_user.id
    db.save_user(user_id, day)
    
    # Set trial start for new users
    db.set_trial_start(user_id)
    
    # Send today's tip + offer in one message
    current_day = db.get_current_day(user_id)
    day_tips = tips.get_tips_for_day(current_day)
    
    if day_tips:
        # Build combined message: tip + offer
        combined_text = f"🌸 *День {current_day} | Тиждень {week}*\n\n"
        
        # Add tip content
        for tip in day_tips:
            if tip.get("title"):
                combined_text += f"*{tip['title']}*\n\n"
            combined_text += tip["text"] + "\n\n"
        
        # Add offer text
        combined_text += msg.ONBOARDING_OFFER
        
        # Send combined message with button
        keyboard = [[InlineKeyboardButton(msg.ONBOARDING_BUTTON_TEXT, url=msg.ONBOARDING_BUTTON_URL)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text=combined_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    return ConversationHandler.END


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset user registration."""
    user_id = update.effective_user.id
    db.delete_user(user_id)
    
    # Show inline buttons for week or day selection
    keyboard = [
        [
            InlineKeyboardButton("📅 Ввести тиждень", callback_data="input_week"),
            InlineKeyboardButton("🗓 Ввести точний день", callback_data="input_day")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Починаємо спочатку!\n\n"
        "Підкажи на якому ти етапі 🌸 Зазвичай достатньо вказати тиждень — але якщо знаєш точний день, можеш одразу його ввести!",
        reply_markup=reply_markup
    )
    await log_user_action(context, user_id, "/restart")
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
    
    # Get subscription info
    sub_info = db.get_user_subscription(user_id)
    subscription_status = sub_info.get("subscription_status") if sub_info else None
    trial_start = sub_info.get("trial_start") if sub_info else None
    subscription_end_date = sub_info.get("subscription_end_date") if sub_info else None
    
    # Calculate trial day if applicable
    trial_day = None
    if trial_start:
        trial_day = (date.today() - trial_start).days + 1
    
    # Log subscription info
    logger.info(
        f"/today for user {user_id}: "
        f"subscription_status={subscription_status!r}, "
        f"trial_start={trial_start}, "
        f"trial_day={trial_day}"
    )
    
    day_tips = tips.get_tips_for_day(current_day)
    
    # Check subscription status and trial
    # Active subscription - send tips
    if subscription_status == 'active':
        if day_tips:
            await send_tips(update.message.chat_id, current_day, day_tips, context)
        else:
            await update.message.reply_text(
                f"На {current_day}-й день у мене немає порад, але я тут! 💛\n"
                "Завтра обов'язково буде щось корисне."
            )
    
    # Trial user (subscription_status is NULL or empty string)
    elif (subscription_status is None or subscription_status == '') and trial_start:
        if trial_day <= 5:
            # Days 1-5: send tip + trial message
            if day_tips:
                await send_tips(update.message.chat_id, current_day, day_tips, context)
                
                if trial_day <= 4:
                    days_left = 5 - trial_day
                    trial_msg = msg.trial_days_left(days_left)
                else:
                    trial_msg = msg.TRIAL_LAST_DAY
                
                keyboard = [[InlineKeyboardButton(msg.SUBSCRIBE_BUTTON_TEXT, url=msg.SUBSCRIBE_BUTTON_URL)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(
                    chat_id=user_id,
                    text=trial_msg,
                    reply_markup=reply_markup
                )
        else:
            # Day 6+: trial ended, don't send tip
            keyboard = [[InlineKeyboardButton(msg.SUBSCRIBE_BUTTON_TEXT, url=msg.SUBSCRIBE_BUTTON_URL)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=user_id,
                text=msg.TRIAL_ENDED,
                reply_markup=reply_markup
            )
    
    # Cancelled subscription
    elif subscription_status == 'cancelled':
        today = datetime.utcnow()
        
        if subscription_end_date and today < subscription_end_date:
            # Still have access - send tips
            if day_tips:
                await send_tips(update.message.chat_id, current_day, day_tips, context)
        else:
            # Access ended
            keyboard = [[InlineKeyboardButton(msg.RENEW_BUTTON_TEXT, url=msg.RENEW_BUTTON_URL)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=user_id,
                text=msg.SUBSCRIPTION_ENDED,
                reply_markup=reply_markup
            )
    
    # Old users without trial_start - send tips normally
    else:
        if day_tips:
            await send_tips(update.message.chat_id, current_day, day_tips, context)
        else:
            await update.message.reply_text(
                f"На {current_day}-й день у мене немає порад, але я тут! 💛\n"
                "Завтра обов'язково буде щось корисне."
            )
    
    await log_user_action(context, user_id, "/today")


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show debug information: send technical data to admins."""
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
    
    # Get user info
    try:
        chat = await context.bot.get_chat(user_id)
        username = chat.username if chat.username else "немає"
    except:
        username = "немає"
    
    # Send technical data to admins
    debug_info = (
        f"🔧 Debug від @{username} (ID: {user_id})\n\n"
        f"👤 User ID: `{user_id}`\n"
        f"👤 Username: @{username}\n"
        f" Поточний день: *{current_day}*\n"
        f"📅 Поточний тиждень: *{current_week}*\n"
        f"📊 Start day: *{user.get('start_day', 'N/A')}*\n"
        f"💡 Кількість порад в базі: *{total_tips}*\n\n"
        f"📋 Дні з порадами:\n`{days_str}`"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=debug_info,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send debug info to admin {admin_id}: {e}")
    
    # Reply to user
    await update.message.reply_text("Щоб твій ботик працював чудово — всі технічні дані відправили адміну 🌸")


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
    """Job: send daily tips to all users with subscription logic."""
    users = db.get_all_users()
    logger.info(f"Sending daily tips to {len(users)} users")

    for user in users:
        user_id = user["user_id"]
        current_day = db.get_current_day(user_id)

        if current_day > 280:
            logger.info(f"User {user_id} finished pregnancy (day {current_day})")
            continue

        # Get subscription info
        sub_info = db.get_user_subscription(user_id)
        subscription_status = sub_info.get("subscription_status") if sub_info else None
        trial_start = sub_info.get("trial_start") if sub_info else None
        subscription_end_date = sub_info.get("subscription_end_date") if sub_info else None

        day_tips = tips.get_tips_for_day(current_day)

        try:
            # Active subscription - send tips without any additions
            if subscription_status == 'active':
                if day_tips:
                    await send_tips(user_id, current_day, day_tips, context)
                    logger.info(f"Sent tips to active subscriber {user_id}")
            
            # Trial user (subscription_status is NULL or empty string)
            elif (subscription_status is None or subscription_status == '') and trial_start:
                trial_day = (date.today() - trial_start).days + 1
                
                if trial_day <= 5:
                    # Days 1-5: send tip + trial message + button
                    if day_tips:
                        await send_tips(user_id, current_day, day_tips, context)
                        
                        if trial_day <= 4:
                            days_left = 5 - trial_day
                            trial_msg = msg.trial_days_left(days_left)
                        else:
                            trial_msg = msg.TRIAL_LAST_DAY
                        
                        keyboard = [[InlineKeyboardButton(msg.SUBSCRIBE_BUTTON_TEXT, url=msg.SUBSCRIBE_BUTTON_URL)]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=trial_msg,
                            reply_markup=reply_markup
                        )
                        logger.info(f"Sent trial day {trial_day} to user {user_id}")
                
                elif trial_day == 6:
                    # Day 6: don't send tip, send trial ended message
                    keyboard = [[InlineKeyboardButton(msg.SUBSCRIBE_BUTTON_TEXT, url=msg.SUBSCRIBE_BUTTON_URL)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=msg.TRIAL_ENDED,
                        reply_markup=reply_markup
                    )
                    logger.info(f"Sent trial ended to user {user_id}")
                
                elif trial_day in [20, 34, 48, 62, 76, 90]:  # Every 14 days after day 6
                    # Reminder every 14 days
                    keyboard = [[InlineKeyboardButton(msg.SUBSCRIBE_BUTTON_TEXT, url=msg.SUBSCRIBE_BUTTON_URL)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=msg.TRIAL_REMINDER,
                        reply_markup=reply_markup
                    )
                    logger.info(f"Sent trial reminder to user {user_id} (day {trial_day})")
            
            # Cancelled subscription
            elif subscription_status == 'cancelled':
                today = datetime.utcnow()
                
                if subscription_end_date and today < subscription_end_date:
                    # Still have access - send tips without additions
                    if day_tips:
                        await send_tips(user_id, current_day, day_tips, context)
                        logger.info(f"Sent tips to cancelled subscriber {user_id} (still has access)")
                else:
                    # Access ended - calculate days since end
                    if subscription_end_date:
                        days_since_end = (today - subscription_end_date).days
                    else:
                        days_since_end = 0
                    
                    # Send reminder on day of expiry and every 14 days
                    if days_since_end == 0 or days_since_end in [14, 28, 42, 56, 70, 84]:
                        keyboard = [[InlineKeyboardButton(msg.RENEW_BUTTON_TEXT, url=msg.RENEW_BUTTON_URL)]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        message_text = msg.SUBSCRIPTION_ENDED if days_since_end == 0 else msg.SUBSCRIPTION_ENDED_REMINDER
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message_text,
                            reply_markup=reply_markup
                        )
                        logger.info(f"Sent subscription ended reminder to user {user_id}")
            
            # Old users without trial_start - send tips normally
            elif not trial_start:
                if day_tips:
                    await send_tips(user_id, current_day, day_tips, context)
                    logger.info(f"Sent tips to legacy user {user_id}")
                    
        except Exception as e:
            logger.error(f"Failed to send to {user_id}: {e}")


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
    
    await log_user_action(context, user_id, "/stop")


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
    
    try:
        users = db.get_all_users_with_details()
        
        if not users:
            await update.message.reply_text("Немає зареєстрованих користувачів.")
            return
        
        # Get user info from Telegram
        users_text = "👥 Список користувачів:\n\n"
        
        for user_data in users[:50]:  # Limit to 50 users per message
            user_id_val = user_data["user_id"]
            current_day = user_data["current_day"]
            current_week = user_data["current_week"]
            last_active = user_data["last_active"]
            status = user_data["status"]
            
            # Try to get user info
            try:
                chat = await context.bot.get_chat(user_id_val)
                username = f"@{chat.username}" if chat.username else "—"
                name = chat.first_name or "—"
            except Exception as e:
                logger.error(f"Failed to get chat info for {user_id_val}: {e}")
                username = "—"
                name = "—"
            
            status_emoji = "✅" if status == "active" else "❌"
            last_active_str = last_active[:10] if last_active else "—"
            
            users_text += (
                f"{status_emoji} {name} ({username})\n"
                f"   День {current_day} | Тиждень {current_week}\n"
                f"   Остання активність: {last_active_str}\n\n"
            )
        
        if len(users) > 50:
            users_text += f"\nПоказано перших 50 з {len(users)} користувачів"
        
        await update.message.reply_text(users_text)
    except Exception as e:
        logger.error(f"Error in users_command: {e}")
        await update.message.reply_text(f"❌ Помилка при отриманні списку користувачів: {e}")


async def admin_reply_callback(query_update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin reply button press."""
    query = query_update.callback_query
    await query.answer()
    
    admin_id = query.from_user.id
    
    # Extract user_id from callback data
    user_id = int(query.data.split("_")[1])
    
    # Get user info
    try:
        chat = await context.bot.get_chat(user_id)
        username = f"@{chat.username}" if chat.username else f"ID: {user_id}"
    except:
        username = f"ID: {user_id}"
    
    # Store user_id in global dict for the reply
    admin_reply_to[admin_id] = user_id
    
    # Send a new message instead of editing (to keep the button)
    await context.bot.send_message(
        chat_id=admin_id,
        text=f"💬 Напишіть вашу відповідь для {username}:"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all non-command text messages."""
    user_id = update.effective_user.id
    
    # Check if this is an admin replying to a user
    if user_id in ADMIN_IDS and user_id in admin_reply_to:
        target_user_id = admin_reply_to[user_id]
        reply_text = update.message.text
        
        # Send reply to user with signature
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"{reply_text}\n\n— команда бота 🌸"
            )
            await update.message.reply_text(f"✅ Відповідь надіслано користувачу!")
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка при відправці: {e}")
        
        # Clear the reply state
        del admin_reply_to[user_id]
        return
    
    # Otherwise, handle as regular user message
    user = db.get_user(user_id)
    
    # Only handle messages from registered users
    if not user or user.get("status") != "active":
        return
    
    # Send confirmation to user
    await update.message.reply_text("Почули тебе 🤍")
    
    # Get user info
    try:
        chat = await context.bot.get_chat(user_id)
        username = f"@{chat.username}" if chat.username else f"ID: {user_id}"
    except:
        username = f"ID: {user_id}"
    
    current_day = db.get_current_day(user_id)
    message_text = update.message.text
    
    # Log user message for watchmode
    text_preview = message_text[:50] if len(message_text) > 50 else message_text
    await log_user_action(context, user_id, f"повідомлення: {text_preview}")
    
    # Forward to admins with reply button
    keyboard = [[InlineKeyboardButton("💬 Відповісти", callback_data=f"reply_{user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    admin_message = (
        f"📩 Повідомлення від {username} (День {current_day}):\n\n"
        f"{message_text}"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to send message to admin {admin_id}: {e}")


async def notify_admins_startup(context: ContextTypes.DEFAULT_TYPE):
    """Notify admins that bot has started."""
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text="🚀 Бот запустився!"
            )
        except Exception as e:
            logger.error(f"Failed to send startup notification to admin {admin_id}: {e}")


async def notify_admins_running(context: ContextTypes.DEFAULT_TYPE):
    """Notify admins that bot is running well."""
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text="✅ Все працює чудово!"
            )
        except Exception as e:
            logger.error(f"Failed to send running notification to admin {admin_id}: {e}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    # Calculate uptime
    if bot_start_time:
        uptime_delta = datetime.now() - bot_start_time
        hours = uptime_delta.seconds // 3600
        minutes = (uptime_delta.seconds % 3600) // 60
        uptime_str = f"{uptime_delta.days * 24 + hours} годин {minutes} хвилин"
    else:
        uptime_str = "невідомо"
    
    status_text = (
        f"⚙️ Статус бота\n\n"
        f"📦 Версія: {VERSION}\n"
        f"📅 Останнє оновлення: {LAST_UPDATE}\n"
        f"📝 Що нового: {CHANGELOG}\n\n"
        f"⏱ Працює: {uptime_str}"
    )
    
    await update.message.reply_text(status_text)


async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reload tips from Google Sheets (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    await update.message.reply_text("🔄 Оновлюю базу порад...")
    
    try:
        tips.reload()
        total_tips = sum(len(tips.data[day]) for day in tips.data)
        total_days = len(tips.data)
        await update.message.reply_text(
            f"✅ База оновлена! Завантажено {total_tips} порад для {total_days} днів"
        )
    except Exception as e:
        logger.error(f"Error reloading tips: {e}")
        await update.message.reply_text(f"❌ Помилка при оновленні: {e}")


async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send maintenance notification to all users (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    maintenance_text = (
        "Дівчатка, зараз ми трішки доналаштовуємо і оновлюємо нашого ботіка 🛠️ "
        "Можливі невеликі збої в наступні кілька годин. "
        "Дякуємо за розуміння — з турботою про вас 🌸"
    )
    
    keyboard = [[InlineKeyboardButton("✅ Підтвердити розсилку", callback_data=f"maintenance_confirm")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📢 Розіслати повідомлення про технічні роботи?\n\n"
        f"{maintenance_text}\n\n"
        f"⚠️ Кнопка підтвердження зникне через 10 секунд",
        reply_markup=reply_markup
    )
    
    # Schedule button removal after 10 seconds
    context.job_queue.run_once(
        lambda ctx: remove_maintenance_button(ctx, update.message.chat_id, update.message.message_id + 1),
        when=10
    )


async def remove_maintenance_button(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    """Remove the maintenance confirmation button after timeout."""
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Failed to remove maintenance button: {e}")


async def maintenance_confirm_callback(query_update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle maintenance broadcast confirmation."""
    query = query_update.callback_query
    await query.answer()
    
    admin_id = query.from_user.id
    
    if admin_id not in ADMIN_IDS:
        await query.edit_message_text("У тебе немає доступу до цієї команди.")
        return
    
    await query.edit_message_text("📤 Розсилаю повідомлення про технічні роботи...")
    
    maintenance_text = (
        "Дівчатка, зараз ми трішки доналаштовуємо і оновлюємо нашого ботіка 🛠️ "
        "Можливі невеликі збої в наступні кілька годин. "
        "Дякуємо за розуміння — з турботою про вас 🌸"
    )
    
    users = db.get_all_users()
    sent_count = 0
    
    for user in users:
        user_id = user["user_id"]
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=maintenance_text,
                disable_notification=True  # Send without sound
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send maintenance message to {user_id}: {e}")
    
    await context.bot.send_message(
        chat_id=admin_id,
        text=f"✅ Розіслано {sent_count} користувачам"
    )


async def watchmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle watchmode for admins to monitor user actions."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    # Toggle watchmode
    if user_id in watchmode_admins:
        watchmode_admins.remove(user_id)
        await update.message.reply_text("👁 Watchmode вимкнено")
    else:
        watchmode_admins.add(user_id)
        await update.message.reply_text("👁 Watchmode увімкнено. Ти будеш отримувати лог всіх дій користувачів в реальному часі.")


async def log_user_action(context: ContextTypes.DEFAULT_TYPE, user_id: int, action: str):
    """Log user action to admins with watchmode enabled."""
    if not watchmode_admins:
        return
    
    # Don't log admin actions
    if user_id in ADMIN_IDS:
        return
    
    # Get user info
    user = db.get_user(user_id)
    if not user:
        return
    
    current_day = db.get_current_day(user_id)
    current_week = (current_day - 1) // 7 + 1
    
    try:
        chat = await context.bot.get_chat(user_id)
        username = chat.username if chat.username else f"ID_{user_id}"
    except:
        username = f"ID_{user_id}"
    
    log_message = f"👁 @{username} (день {current_day}, тиж {current_week}): {action}"
    
    for admin_id in watchmode_admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=log_message
            )
        except Exception as e:
            logger.error(f"Failed to send watchmode log to admin {admin_id}: {e}")


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unsubscribe command - request to cancel subscription."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user or user.get("status") != "active":
        await update.message.reply_text(msg.NOT_REGISTERED)
        return
    
    # Get subscription info
    sub_info = db.get_user_subscription(user_id)
    subscription_status = sub_info.get("subscription_status") if sub_info else None
    
    # Check subscription status
    if subscription_status == 'active':
        # Show confirmation buttons for active subscription
        keyboard = [
            [
                InlineKeyboardButton(msg.UNSUBSCRIBE_BUTTON_YES, callback_data="unsubscribe_yes"),
                InlineKeyboardButton(msg.UNSUBSCRIBE_BUTTON_NO, callback_data="unsubscribe_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(msg.UNSUBSCRIBE_CONFIRM, reply_markup=reply_markup)
        await log_user_action(context, user_id, "/unsubscribe")
    
    elif subscription_status == 'cancelled':
        # Already cancelled
        await update.message.reply_text("Твоя підписка вже скасована 🌸")
        await log_user_action(context, user_id, "/unsubscribe (вже скасована)")
    
    else:
        # No subscription (NULL or empty)
        await update.message.reply_text("У тебе ще немає підписки 🌸")
        await log_user_action(context, user_id, "/unsubscribe (немає підписки)")


async def unsubscribe_callback(query_update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unsubscribe confirmation buttons."""
    query = query_update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == "unsubscribe_no":
        # User cancelled unsubscribe - delete message and send new one
        try:
            await query.message.delete()
        except:
            pass
        
        await context.bot.send_message(
            chat_id=user_id,
            text=msg.UNSUBSCRIBE_CANCELLED
        )
        await log_user_action(context, user_id, "unsubscribe: скасовано")
    
    elif query.data == "unsubscribe_yes":
        # User confirmed unsubscribe
        await query.edit_message_text(msg.UNSUBSCRIBE_CONFIRMED)
        
        # Get user info for admin notification
        sub_info = db.get_user_subscription(user_id)
        zenedu_subscriber_id = sub_info.get("zenedu_subscriber_id") if sub_info else None
        
        try:
            chat = await context.bot.get_chat(user_id)
            username = chat.username if chat.username else "немає"
            name = f"{chat.first_name or ''} {chat.last_name or ''}".strip() or "Без імені"
        except:
            username = "немає"
            name = "Без імені"
        
        # Escape special characters for HTML
        name_escaped = html.escape(name)
        
        # Get ZENEDU_BOT_ID from environment
        zenedu_bot_id = os.environ.get("ZENEDU_BOT_ID", "")
        
        # Format timestamp
        timestamp = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        
        # Build admin notification with HTML and clickable link
        if zenedu_subscriber_id and zenedu_bot_id:
            subscriber_link = f"https://app.zenedu.io/bot/{zenedu_bot_id}/subscribers/{zenedu_subscriber_id}"
            admin_notification = (
                f"🔔 Запит на скасування підписки\n\n"
                f"👤 <a href=\"{subscriber_link}\">{name_escaped}</a>\n"
                f"📱 @{username} | ID: {user_id}\n"
                f"📅 {timestamp}"
            )
        else:
            admin_notification = (
                f"🔔 Запит на скасування підписки\n\n"
                f"👤 {name_escaped}\n"
                f"📱 @{username} | ID: {user_id}\n"
                f"📅 {timestamp}"
            )
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_notification,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send unsubscribe notification to admin {admin_id}: {e}")
        
        await log_user_action(context, user_id, "unsubscribe: підтверджено")


async def deleteuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete user from database (admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У тебе немає доступу до цієї команди.")
        return
    
    # Get user_id from command arguments
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Використання: /deleteuser <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Невірний user_id. Має бути число.")
        return
    
    # Check if user exists
    user = db.get_user(target_user_id)
    if not user:
        await update.message.reply_text(f"❌ Юзер {target_user_id} не знайдений")
        return
    
    # Delete user
    db.delete_user(target_user_id)
    await update.message.reply_text(f"✅ Юзер {target_user_id} видалений")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Добре, до зустрічі! 👋")
    return ConversationHandler.END


async def run_webhook_server():
    """Run the aiohttp webhook server."""
    port = int(os.environ.get("PORT", 8080))
    webhook_app = await zenedu_webhook.create_webhook_app()
    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Webhook server started on port {port}")


async def main_async():
    """Main async function to run both bot and webhook server."""
    global bot_start_time
    bot_start_time = datetime.now()
    
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    # Load tips on startup
    tips.load()
    logger.info(f"Loaded tips for {len(tips.data)} days")

    app = Application.builder().token(token).build()
    
    # Set bot application, watchmode_admins, and db in webhook module
    zenedu_webhook.bot_application = app
    zenedu_webhook.watchmode_admins = watchmode_admins
    zenedu_webhook.db = db

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("restart", restart),
        ],
        states={
            ASK_DAY: [
                CallbackQueryHandler(button_callback, pattern="^(input_week|input_day)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_day)
            ],
            ASK_WEEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_week)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("debug", debug_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("reload", reload_command))
    app.add_handler(CommandHandler("maintenance", maintenance_command))
    app.add_handler(CommandHandler("watchmode", watchmode_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("deleteuser", deleteuser_command))
    # Handle admin reply button
    app.add_handler(CallbackQueryHandler(admin_reply_callback, pattern="^reply_"))
    app.add_handler(CallbackQueryHandler(maintenance_confirm_callback, pattern="^maintenance_confirm$"))
    app.add_handler(CallbackQueryHandler(unsubscribe_callback, pattern="^unsubscribe_"))
    
    # Handle all non-command text messages (both user messages and admin replies)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Schedule tips every 2 hours (test mode: 2 hours = 1 day)
    job_queue = app.job_queue
    
    # Calculate time until next scheduled run (e.g., 9:00 AM Kyiv time)
    now = datetime.now(KYIV_TZ)
    target_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    
    # If we've passed 9 AM today, schedule for tomorrow
    if now.time() >= time(9, 0):
        target_time += timedelta(days=1)
    
    # Calculate seconds until target time
    time_until_first = (target_time - now).total_seconds()
    
    job_queue.run_repeating(
        send_daily_tips,
        interval=7200,  # 2 hours in seconds (test mode)
        first=time_until_first,  # Wait until scheduled time
        name="tips_every_2_hours"
    )
    
    logger.info(f"Scheduled daily tips to start at {target_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # Notify admins on startup
    job_queue.run_once(notify_admins_startup, when=1)  # Immediately after startup
    job_queue.run_once(notify_admins_running, when=60)  # After 1 minute

    logger.info("Bot started!")
    
    # Start webhook server
    await run_webhook_server()
    
    # Initialize and run the bot
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep running
        await asyncio.Event().wait()


def main():
    """Entry point."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

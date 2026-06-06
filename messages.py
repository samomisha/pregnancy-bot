# All bot messages in one place for easy editing

# Onboarding messages
ONBOARDING_WELCOME = """Привіт! 👋 Я твій помічник для вагітних 🤰

Щодня я надсилатиму тобі корисні поради відповідно до твого терміну.

Підкажи на якому ти етапі 🌸 Зазвичай достатньо вказати тиждень — але якщо знаєш точний день, можеш одразу його ввести!"""

ONBOARDING_WEEK_PROMPT = "📅 Чудово! Напиши номер тижня від 1 до 40:"

ONBOARDING_DAY_PROMPT = "🗓 Чудово! Напиши день вагітності від 1 до 280:"

def onboarding_confirmation(day, week):
    return f"""✅ Чудово! Я запам'ятала, що ти на {day}-му дні ({week}-й тиждень).

Щодня о 9:00 ранку тобі приходитиме порада 💛

Напиши /today щоб отримати сьогоднішню пораду прямо зараз!"""

ONBOARDING_OFFER = """🌸 Щоб отримувати щоденні поради протягом усієї вагітності, спробуй повний доступ всього за 1 грн!

Перші 5 днів — безкоштовно, потім 99 грн/міс."""

ONBOARDING_BUTTON_TEXT = "Спробувати за 1 грн"
ONBOARDING_BUTTON_URL = "https://app.zenedu.io/l/x6PTPdiqsZpglKGo"

# Trial messages
def trial_days_left(days_left):
    if days_left == 1:
        return "Залишився 1 день безкоштовного доступу 🌸"
    elif days_left in [2, 3, 4]:
        return f"Залишилось {days_left} дні безкоштовного доступу 🌸"
    else:
        return f"Залишилось {days_left} днів безкоштовного доступу 🌸"

TRIAL_LAST_DAY = "Це остання безкоштовна порада 🌸"

TRIAL_ENDED = """Твій безкоштовний доступ закінчився 🌸

Щоб продовжити отримувати щоденні поради — оформи підписку."""

TRIAL_REMINDER = """Нагадуємо, що твій безкоштовний доступ закінчився 🌸

Щоб продовжити отримувати щоденні поради — оформи підписку."""

SUBSCRIBE_BUTTON_TEXT = "Підписатись"
SUBSCRIBE_BUTTON_URL = "https://app.zenedu.io/l/1HZejLHnHqxJltIg"

# Subscription cancelled messages
SUBSCRIPTION_ENDED = """Твоя підписка закінчилась 🌸

Щоб продовжити отримувати щоденні поради — поновіть підписку."""

SUBSCRIPTION_ENDED_REMINDER = """Нагадуємо, що твоя підписка закінчилась 🌸

Щоб продовжити отримувати щоденні поради — поновіть підписку."""

RENEW_BUTTON_TEXT = "Поновити"
RENEW_BUTTON_URL = "https://app.zenedu.io/l/1HZejLHnHqxJltIg"

# Unsubscribe messages
UNSUBSCRIBE_CONFIRM = "Ти впевнена що хочеш скасувати підписку?"

UNSUBSCRIBE_BUTTON_YES = "Так, скасувати"
UNSUBSCRIBE_BUTTON_NO = "Ні, залишити"

UNSUBSCRIBE_CANCELLED = """Чудово! Твоя підписка залишається активною 💛

Продовжуй отримувати щоденні поради для твоєї вагітності 🌸"""

COURSE_BOT_LINK = "https://t.me/SAMOVAROV_bot"

UNSUBSCRIBE_CONFIRMED = f"""Ми отримали твій запит на скасування підписки.

Ти можеш скасувати підписку самостійно в боті з курсом ({COURSE_BOT_LINK}), але ми також скасуємо її вручну.

Якщо пройшов зайвий платіж — зробимо повернення 💛"""

def unsubscribe_admin_notification(name, username, user_id, zenedu_subscriber_id, zenedu_bot_id, timestamp):
    subscriber_link = f"https://app.zenedu.io/bot/{zenedu_bot_id}/subscribers/{zenedu_subscriber_id}" if zenedu_subscriber_id else "немає"
    return f"""🔔 Запит на скасування підписки

👤 [{name}]({subscriber_link})
📱 @{username} | ID: {user_id}
📅 {timestamp}"""

# Other messages
ALREADY_REGISTERED = """👶 Ти вже зареєстрована! Щодня о 9:00 тобі приходитиме порада.

Якщо хочеш змінити термін — напиши /restart
Якщо хочеш відписатися — напиши /stop"""

NOT_REGISTERED = "Ти ще не зареєстрована! Напиши /start щоб розпочати 🌸"

NO_TIPS_TODAY = lambda day: f"На {day}-й день у мене немає порад, але я тут! 💛\nЗавтра обов'язково буде щось корисне."

MESSAGE_RECEIVED = "Почули тебе 🤍"

RESTART_PROMPT = """Починаємо спочатку!

Підкажи на якому ти етапі 🌸 Зазвичай достатньо вказати тиждень — але якщо знаєш точний день, можеш одразу його ввести!"""

STOP_CONFIRMED = """😔 Ти відписалася від щоденних порад.

Якщо захочеш повернутися — просто напиши /start"""

DEBUG_SENT = "Щоб твій ботик працював чудово — всі технічні дані відправили адміну 🌸"

# Subscription activated message
SUBSCRIPTION_ACTIVATED = """Вітаємо! 🎉 Твоя підписка активована 💛

Щодня о 9:00 ранку тобі приходитиме порада відповідно до твого терміну.

Якщо виникнуть питання — пиши, ми завжди на зв'язку 🌸"""

import json
import logging
from aiohttp import web
from datetime import datetime

logger = logging.getLogger(__name__)

# Will be set from bot.py
bot_application = None
watchmode_admins = None
db = None


async def handle_zenedu_webhook(request):
    """Handle incoming webhook from Zenedu."""
    try:
        # Parse JSON payload
        payload = await request.json()
        
        # Extract event name if available
        event_name = payload.get('event', 'Unknown Event')
        
        # Format JSON beautifully for watchmode admins
        formatted_json = json.dumps(payload, indent=2, ensure_ascii=False)
        
        # Create message for admins in watchmode
        message = f"🔔 Zenedu Webhook\nEvent: {event_name}\n---\n{formatted_json}"
        
        # Send to admins in watchmode
        if watchmode_admins and bot_application:
            for admin_id in watchmode_admins:
                try:
                    await bot_application.bot.send_message(
                        chat_id=admin_id,
                        text=message
                    )
                    logger.info(f"Sent Zenedu webhook to admin {admin_id}")
                except Exception as e:
                    logger.error(f"Failed to send webhook to admin {admin_id}: {e}")
        
        # Process subscription events
        if db:
            await process_subscription_event(payload, event_name)
        
        # Return success response
        return web.json_response({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Error handling Zenedu webhook: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def process_subscription_event(payload, event_name):
    """Process subscription-related events from Zenedu."""
    try:
        # Event: product.subscriber.added - new subscriber
        if event_name == "product.subscriber.added":
            user_id = payload.get("data", {}).get("user_id")
            subscriber_id = payload.get("data", {}).get("id")
            
            if user_id and subscriber_id:
                # Check if user exists in database
                user = db.get_user(user_id)
                if user:
                    db.update_subscription(
                        user_id=user_id,
                        zenedu_subscriber_id=subscriber_id,
                        subscription_status='active',
                        subscription_end_date=None
                    )
                    logger.info(f"Activated subscription for user {user_id}, subscriber_id {subscriber_id}")
                    
                    # Send welcome message to user
                    if bot_application:
                        try:
                            # Import messages module
                            import messages as msg
                            await bot_application.bot.send_message(
                                chat_id=user_id,
                                text=msg.SUBSCRIPTION_ACTIVATED
                            )
                            logger.info(f"Sent subscription activated message to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to send subscription activated message to user {user_id}: {e}")
                else:
                    logger.warning(f"User {user_id} not found in database, ignoring subscription event")
        
        # Event: order.status.changed with status=paid and type=subscription_renew
        elif event_name == "order.status.changed":
            data = payload.get("data", {})
            status = data.get("status")
            order_type = data.get("type")
            
            if status == "paid" and order_type == "subscription_renew":
                subscriber = data.get("subscriber", {})
                user_id = subscriber.get("user_id")
                
                if user_id:
                    user = db.get_user(user_id)
                    if user:
                        db.update_subscription(
                            user_id=user_id,
                            subscription_status='active',
                            subscription_end_date=None
                        )
                        logger.info(f"Renewed subscription for user {user_id}")
                    else:
                        logger.warning(f"User {user_id} not found in database, ignoring renewal event")
        
        # Event: subscription.cancelled
        elif event_name == "subscription.cancelled":
            data = payload.get("data", {})
            subscriber = data.get("subscriber", {})
            user_id = subscriber.get("user_id")
            expired_at = data.get("expired_at")
            
            if user_id:
                user = db.get_user(user_id)
                if user:
                    # Parse expired_at timestamp
                    end_date = None
                    end_date_formatted = "невідомо"
                    if expired_at:
                        try:
                            end_date = datetime.fromisoformat(expired_at.replace('Z', '+00:00'))
                            end_date_formatted = end_date.strftime("%d.%m.%Y")
                        except:
                            logger.error(f"Failed to parse expired_at: {expired_at}")
                    
                    db.update_subscription(
                        user_id=user_id,
                        subscription_status='cancelled',
                        subscription_end_date=end_date
                    )
                    logger.info(f"Cancelled subscription for user {user_id}, expires at {expired_at}")
                    
                    # Send notification to user
                    if bot_application:
                        try:
                            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                            
                            message_text = (
                                f"Твою підписку скасовано 💛 Поради будуть приходити до {end_date_formatted}. "
                                f"Якщо передумаєш — завжди можна поновити 🌸"
                            )
                            
                            keyboard = [[InlineKeyboardButton("Поновити", url="https://app.zenedu.io/l/1HZejLHnHqxJltIg")]]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            await bot_application.bot.send_message(
                                chat_id=user_id,
                                text=message_text,
                                reply_markup=reply_markup
                            )
                            logger.info(f"Sent subscription cancelled message to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to send subscription cancelled message to user {user_id}: {e}")
                else:
                    logger.warning(f"User {user_id} not found in database, ignoring cancellation event")
    
    except Exception as e:
        logger.error(f"Error processing subscription event: {e}")


async def create_webhook_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_post('/webhook/zenedu', handle_zenedu_webhook)
    return app

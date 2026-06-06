import json
import logging
import os
from aiohttp import web
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Will be set from bot.py
bot_application = None
watchmode_admins = None
db = None

# Stats cache
stats_cache = {
    "data": None,
    "generated_at": None
}
CACHE_DURATION = timedelta(hours=1)


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
                    
                    # Track first payment and add event
                    db.set_first_paid(user_id)
                    db.add_subscription_event(user_id, 'activated')
                    
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
                price = data.get("price")
                
                if user_id:
                    user = db.get_user(user_id)
                    if user:
                        db.update_subscription(
                            user_id=user_id,
                            subscription_status='active',
                            subscription_end_date=None
                        )
                        
                        # Add renewal event with amount
                        db.add_subscription_event(user_id, 'renewed', amount=price)
                        
                        logger.info(f"Renewed subscription for user {user_id}, amount {price}")
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
                    
                    # Add cancellation event
                    db.add_subscription_event(user_id, 'cancelled')
                    
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


async def handle_stats(request):
    """Handle stats API endpoint with token authentication and caching."""
    try:
        # Check token
        token = request.query.get('token')
        expected_token = os.environ.get('STATS_TOKEN')
        
        if not expected_token:
            logger.error("STATS_TOKEN environment variable not set")
            return web.json_response({"error": "Stats endpoint not configured"}, status=500)
        
        if token != expected_token:
            logger.warning(f"Invalid stats token attempt: {token}")
            return web.json_response({"error": "Unauthorized"}, status=401)
        
        # Check cache
        now = datetime.utcnow()
        if stats_cache["data"] and stats_cache["generated_at"]:
            cache_age = now - stats_cache["generated_at"]
            if cache_age < CACHE_DURATION:
                logger.info(f"Returning cached stats (age: {cache_age.total_seconds():.0f}s)")
                return web.json_response(stats_cache["data"])
        
        # Generate fresh stats
        if not db:
            return web.json_response({"error": "Database not available"}, status=500)
        
        logger.info("Generating fresh stats")
        analytics = db.get_analytics_stats()
        
        # Build response
        response_data = {
            "funnel": {
                "total_users": analytics['funnel']['total_registered'],
                "term_entered": analytics['funnel']['entered_term'],
                "trial_started": analytics['funnel']['started_trial'],
                "paid": analytics['funnel']['first_paid'],
                "conv_term_pct": analytics['funnel']['conv_term'],
                "conv_trial_pct": analytics['funnel']['conv_trial'],
                "conv_paid_pct": analytics['funnel']['conv_paid']
            },
            "subscriptions": {
                "active_subscriptions": analytics['subscriptions']['active'],
                "mrr": analytics['subscriptions']['mrr'],
                "total_paid": analytics['subscriptions']['total_ever_paid']
            },
            "activity": {
                "wau": analytics['activity']['wau']
            },
            "retention": {
                "month_1": analytics['retention'].get('month_1', {}),
                "month_2": analytics['retention'].get('month_2', {}),
                "month_3": analytics['retention'].get('month_3', {}),
                "month_4": analytics['retention'].get('month_4', {})
            },
            "generated_at": now.isoformat() + "Z"
        }
        
        # Update cache
        stats_cache["data"] = response_data
        stats_cache["generated_at"] = now
        
        return web.json_response(response_data)
        
    except Exception as e:
        logger.error(f"Error handling stats request: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def create_webhook_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_post('/webhook/zenedu', handle_zenedu_webhook)
    app.router.add_get('/api/stats', handle_stats)
    return app

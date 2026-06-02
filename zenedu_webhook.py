import json
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

# Will be set from bot.py
bot_application = None
watchmode_admins = None


async def handle_zenedu_webhook(request):
    """Handle incoming webhook from Zenedu."""
    try:
        # Parse JSON payload
        payload = await request.json()
        
        # Extract event name if available
        event_name = payload.get('event', 'Unknown Event')
        
        # Format JSON beautifully
        formatted_json = json.dumps(payload, indent=2, ensure_ascii=False)
        
        # Create message for admins
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
        else:
            logger.warning("No admins in watchmode or bot_application not set")
        
        # Return success response
        return web.json_response({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Error handling Zenedu webhook: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def create_webhook_app():
    """Create and configure the aiohttp application."""
    app = web.Application()
    app.router.add_post('/webhook/zenedu', handle_zenedu_webhook)
    return app

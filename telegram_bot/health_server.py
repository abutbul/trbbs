import asyncio
import logging
import json
from aiohttp import web
from telegram_bot.core.status import service_status
from telegram_bot.core.config import HEALTH_SERVER_HOST, HEALTH_SERVER_PORT

logger = logging.getLogger(__name__)

# Global reference to the app runner
app_runner = None

async def health_handler(request):
    """Handle health check requests."""
    status = service_status.get_status()
    
    # Determine overall health
    is_healthy = (
        status["telegram_connected"] and
        status["redis_connected"] and
        not status["startup_phase"]
    )
    
    # Return appropriate status code based on health
    if is_healthy:
        return web.json_response(status)
    else:
        return web.json_response(status, status=503)  # Service Unavailable

async def start_health_server():
    """Start the health check server."""
    global app_runner
    
    try:
        # Create app
        app = web.Application()
        app.add_routes([web.get('/health', health_handler)])
        
        # Start the server
        app_runner = web.AppRunner(app)
        await app_runner.setup()
        site = web.TCPSite(app_runner, HEALTH_SERVER_HOST, HEALTH_SERVER_PORT)
        await site.start()
        
        logger.info(f"Health server started on http://{HEALTH_SERVER_HOST}:{HEALTH_SERVER_PORT}/health")
        
        # Keep the server running
        while True:
            await asyncio.sleep(3600)  # Just keep the task alive
            
    except asyncio.CancelledError:
        logger.info("Health server task cancelled")
    except Exception as e:
        logger.error(f"Error in health server: {e}")
    finally:
        await stop_health_server()

async def stop_health_server():
    """Stop the health check server."""
    global app_runner
    
    if app_runner:
        try:
            logger.info("Stopping health server...")
            await app_runner.cleanup()
            app_runner = None
            logger.info("Health server stopped")
        except Exception as e:
            logger.error(f"Error stopping health server: {e}")

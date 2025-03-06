#!/usr/bin/env python3
import os
import logging
import asyncio
import sys
import time
import signal
import json
from aiohttp import web

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

# Import modules from our new structure
from bot_logic.core.status import service_status
from bot_logic.core.config import DEBUG_MODE
from bot_logic.services.redis_service import initialize_redis, cleanup_redis
from bot_logic.handlers.message_listener import message_listener
from bot_logic.services.chat_api_queue import start_queue_processor, stop_queue_processor
# Import the new reaction handler
from bot_logic.services.reaction_handler import start_reaction_handler, stop_reaction_handler

# Create web app for health checks
app = web.Application()

async def health_handler(request):
    """Health check endpoint for the service."""
    # Get status information
    status = service_status.get_status()
    
    # Determine overall health
    status['healthy'] = status.get('redis_connected', False)
    
    if status['healthy']:
        return web.json_response(status)
    else:
        return web.json_response(status, status=503)  # Service Unavailable

# Register routes
app.router.add_get('/health', health_handler)

async def start_web_server():
    """Start the health check web server."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8081)
    await site.start()
    logger.info("Health check server started on http://0.0.0.0:8081")
    return runner

async def cleanup(runner, listener_task):
    """Clean up resources before shutdown."""
    if runner:
        await runner.cleanup()
    
    if listener_task:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
    
    await cleanup_redis()
    logger.info("Cleanup completed")

# Flag to track if we should shut down
should_shutdown = False

# Get environment variable for queue worker
ENABLE_QUEUE_WORKER = os.environ.get("ENABLE_QUEUE_WORKER", "true").lower() == "true"

async def main():
    """Main entry point of the service."""
    instance_name = os.environ.get("INSTANCE_NAME", "bot-logic-unknown")
    logger.info(f"Starting bot logic service [{instance_name}]")
    
    # Initialize Redis
    if not await initialize_redis():
        logger.critical("Failed to connect to Redis, exiting")
        return 1
    
    # Start the web server for health checks
    web_runner = await start_web_server()
    
    # Only start the queue processor if enabled for this instance
    if ENABLE_QUEUE_WORKER:
        logger.info("Starting chat API queue processor for this instance")
        await start_queue_processor()
    else:
        logger.info("Chat API queue processor not enabled for this instance")
    
    # Start reaction handler (new!)
    await start_reaction_handler()
    
    # Start message listener
    listener = asyncio.create_task(message_listener())
    
    # Wait for shutdown signal
    shutdown = asyncio.Future()
    
    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: shutdown.set_result(None))
    
    try:
        await shutdown
        logger.info("Shutdown signal received")
    finally:
        await cleanup(web_runner, listener)
        
        # Stop queue processor if it was enabled
        if ENABLE_QUEUE_WORKER:
            await stop_queue_processor()
        
        # Stop the reaction handler (new!)
        await stop_reaction_handler()
    
    return 0

def signal_handler():
    """Handle termination signals."""
    global should_shutdown
    logger.info("Received termination signal, shutting down...")
    should_shutdown = True

# Register signal handlers for graceful shutdown
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda signum, frame: signal_handler())

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        exit_code = 1
    finally:
        logger.info(f"Bot logic service shutting down with exit code {exit_code}")

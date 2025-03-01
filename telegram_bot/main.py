import asyncio
import logging
import signal
import sys
from telegram_bot.core.status import service_status
from telegram_bot.core.config import DEBUG_MODE
from telegram_bot.health_server import start_health_server, stop_health_server
from telegram_bot.handlers.update_checker import update_monitor
from telegram_bot.handlers.response_handler import response_listener
from telegram_bot.services.telegram_service import initialize_bots, shutdown_bots

logger = logging.getLogger(__name__)

# Track running tasks
health_task = None
update_task = None
response_task = None

async def run_bot():
    """Run the Telegram bot service."""
    global health_task, update_task, response_task
    
    try:
        logger.info("Starting Telegram bot services...")
        
        # Start health check server
        health_task = asyncio.create_task(start_health_server())
        
        # Wait for any previous bot sessions to expire
        logger.info("Waiting for any previous bot sessions to expire...")
        await asyncio.sleep(10)
        
        # Initialize Telegram bot(s)
        retry_count = 0
        while retry_count < 3:
            bot_init_success = await initialize_bots()
            if bot_init_success:
                break
            
            logger.warning(f"Bot initialization attempt {retry_count + 1} failed, retrying...")
            retry_count += 1
            await asyncio.sleep(10)  # Longer wait between retries
        
        if not bot_init_success:
            logger.error("Failed to initialize any Telegram bots after multiple attempts. Exiting...")
            # Force exit on initialization failure
            sys.exit(1)
            return False
        
        # Allow time for bot initialization to complete
        logger.info("Waiting for bot initialization to settle...")
        await asyncio.sleep(5)
        
        # Start the update monitor
        logger.info("Starting update monitor...")
        update_task = asyncio.create_task(update_monitor())
        await asyncio.sleep(2)  # Give update monitor time to start
        
        # Start the response listener
        logger.info("Starting response listener...")
        response_task = asyncio.create_task(response_listener())
        
        # Mark startup as complete
        service_status.complete_startup()
        logger.info("Telegram bot services started successfully")
        
        return True
        
    except Exception as e:
        logger.error(f"Error starting bot services: {e}")
        return False

async def shutdown():
    """Gracefully shut down all services."""
    logger.info("Shutting down Telegram bot services...")
    
    # Cancel all running tasks
    if update_task:
        update_task.cancel()
        try:
            await update_task
        except asyncio.CancelledError:
            pass
    
    if response_task:
        response_task.cancel()
        try:
            await response_task
        except asyncio.CancelledError:
            pass
    
    # Shutdown bot
    await shutdown_bots()
    
    # Stop health server
    await stop_health_server()
    
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    
    logger.info("All services have been shut down")

async def run_with_shutdown_handling():
    """Run the bot with proper signal handling."""
    loop = asyncio.get_running_loop()
    
    # Set up signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    
    try:
        success = await run_bot()
        if not success:
            logger.error("Bot initialization failed, shutting down...")
            await shutdown()
            return
        
        # Keep the main task running
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    finally:
        await shutdown()

def run():
    """Entry point for the bot service."""
    try:
        if DEBUG_MODE:
            logger.info("Running in DEBUG mode")
        
        # Use asyncio.run to properly manage the event loop
        asyncio.run(run_with_shutdown_handling())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run()
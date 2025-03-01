#!/usr/bin/env python3
import os
import logging
import asyncio
import sys

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

async def main():
    """Main entry point."""
    try:
        logger.info("Starting Bot Logic service...")
        
        # Initialize the Redis connection
        redis = await initialize_redis()
        if not redis:
            logger.error("Failed to initialize Redis connection. Exiting...")
            return False
        
        # Mark startup as complete
        service_status.complete_startup()
        logger.info("Bot Logic service started successfully")
        
        # Start message listener
        await message_listener()
        
        return True
    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        raise
    finally:
        # Clean up Redis connection when exiting
        await cleanup_redis()

async def run_with_shutdown_handling():
    """Run the service with proper signal handling."""
    import signal
    loop = asyncio.get_running_loop()
    
    # Set up signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(cleanup_redis()))
    
    try:
        success = await main()
        if not success:
            logger.error("Service initialization failed")
            return
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    finally:
        await cleanup_redis()

if __name__ == "__main__":
    try:
        if DEBUG_MODE:
            logger.info("Running in DEBUG mode")
        
        # Use asyncio.run to properly manage the event loop
        asyncio.run(run_with_shutdown_handling())
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)

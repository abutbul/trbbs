import asyncio
import logging
import os
import sys
import signal
import json
import time  # Add missing import for time.time()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

# Import modules
from telegram_pubsub.message_listener import message_listener
from telegram_pubsub.response_listener import response_listener
from telegram_pubsub.reaction_listener import reaction_listener

# Flag for enabling reaction handling - default to TRUE
ENABLE_REACTIONS = os.environ.get("ENABLE_REACTIONS", "true").lower() == "true"

# Globals to track tasks
message_task = None
response_task = None
reaction_task = None

async def check_reaction_channel():
    """Check if the reaction channel is working properly."""
    try:
        # Get Redis configuration from environment
        redis_host = os.environ.get("REDIS_HOST", "redis")
        redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        redis_password = os.environ.get("REDIS_PASSWORD", "")
        redis_db = int(os.environ.get("REDIS_DB", "0"))
        redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
        
        # Connect to Redis
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            redis_url,
            decode_responses=True
        )
        
        # Test publishing and subscribing
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("message_reactions")
        
        # Publish a test message
        test_message = {
            "test": True,
            "timestamp": time.time()
        }
        
        result = await redis_client.publish("message_reactions", json.dumps(test_message))
        logger.info(f"Test publish to message_reactions, result: {result}")
        
        # Wait briefly
        await asyncio.sleep(1)
        
        # Check for received message
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
        if message:
            logger.info("Successfully received test message on message_reactions channel")
        else:
            logger.warning("Did not receive test message on message_reactions channel")
        
        # Clean up
        await pubsub.unsubscribe()
        await redis_client.close()
        
    except Exception as e:
        logger.error(f"Error checking reaction channel: {e}")

async def main():
    """Main entry point for Telegram PubSub service."""
    global message_task, response_task, reaction_task
    
    logger.info("Starting Telegram PubSub service")
    
    # Check reaction channel first
    if ENABLE_REACTIONS:
        logger.info("Checking reaction channel...")
        await check_reaction_channel()
    
    # Start message listener
    message_task = asyncio.create_task(message_listener())
    logger.info("Started message listener")
    
    # Start response listener
    response_task = asyncio.create_task(response_listener())
    logger.info("Started response listener")
    
    # Start reaction listener if enabled
    if ENABLE_REACTIONS:
        reaction_task = asyncio.create_task(reaction_listener())
        logger.info("Started reaction listener")
    else:
        logger.warning("Reaction handling is disabled! Set ENABLE_REACTIONS=true to enable it.")
    
    # Handle termination signals
    shutdown = asyncio.Future()
    
    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: shutdown.set_result(None))
    
    # Wait for shutdown signal
    await shutdown
    
    # Clean up on shutdown
    logger.info("Shutting down...")
    
    # Cancel all tasks
    for task in [task for task in [message_task, response_task, reaction_task] if task]:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    logger.info("Shutdown complete")
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        exit_code = 1
    finally:
        logger.info(f"Service exiting with code {exit_code}")
        sys.exit(exit_code)

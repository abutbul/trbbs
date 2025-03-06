import json
import logging
import asyncio
import redis.asyncio as aioredis
import os
import time
from .reaction_handler import handle_reaction

logger = logging.getLogger(__name__)

# Get Redis configuration from environment
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

async def reaction_listener():
    """Listen for reaction messages on Redis and process them."""
    reconnect_delay = 5  # Start with a short delay
    max_reconnect_delay = 60  # Maximum reconnect delay
    redis_client = None
    pubsub = None
    
    logger.info("Starting reaction listener...")
    
    while True:  # Keep trying to reconnect
        try:
            # Connect to Redis if not connected
            if redis_client is None:
                logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
                redis_client = aioredis.from_url(
                    REDIS_URL,
                    decode_responses=True
                )
                
                # Check connection
                await redis_client.ping()
                logger.info("Successfully connected to Redis")
                
                # Create PubSub
                pubsub = redis_client.pubsub()
                
                # Subscribe to channel
                logger.info("Subscribing to message_reactions channel...")
                await pubsub.subscribe("message_reactions")
                logger.info("Successfully subscribed to message_reactions channel")
                
                # Verify subscription
                channels = await pubsub.channels("message_reactions")
                if channels:
                    logger.info(f"Confirmed subscription to channels: {channels}")
                else:
                    logger.warning("Could not confirm subscription to message_reactions channel")
                
                # Reset reconnect delay on successful connection
                reconnect_delay = 5
                
                # Send a test message to self to verify the channel is working
                test_data = {
                    "test": True,
                    "timestamp": time.time()
                }
                result = await redis_client.publish("message_reactions", json.dumps(test_data))
                logger.info(f"Test message published to message_reactions, receivers: {result}")
            
            # Listen for messages
            while True:
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
                    if message and message["type"] == "message":
                        logger.debug(f"Received reaction message: {message}")
                        
                        try:
                            data = json.loads(message["data"])
                            
                            # Skip test messages
                            if data.get("test"):
                                logger.debug("Skipping test message")
                                continue
                                
                            # Handle actual reaction
                            logger.info(f"Processing reaction: {data.get('emoji')} for message {data.get('message_id')}")
                            await handle_reaction(data)
                            
                        except json.JSONDecodeError:
                            logger.error("Invalid JSON in reaction message")
                        except Exception as e:
                            logger.error(f"Error handling reaction: {e}", exc_info=True)
                    
                    # Small delay to prevent CPU hogging
                    await asyncio.sleep(0.1)
                    
                except asyncio.CancelledError:
                    logger.info("Reaction listener task cancelled")
                    # Clean up Redis connections
                    await pubsub.unsubscribe()
                    await redis_client.close()
                    return
                    
                except Exception as e:
                    logger.error(f"Error in reaction listen loop: {e}", exc_info=True)
                    # Break inner loop to reconnect
                    redis_client = None
                    break
                    
        except asyncio.CancelledError:
            logger.info("Reaction listener task cancelled")
            # Clean up Redis connections
            if pubsub:
                await pubsub.unsubscribe()
            if redis_client:
                await redis_client.close()
            return
            
        except Exception as e:
            logger.error(f"Error in reaction listener: {e}", exc_info=True)
            
            # Clean up Redis connections
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                except:
                    pass
            if redis_client:
                try:
                    await redis_client.close()
                except:
                    pass
            
            redis_client = None
            
            # Exponential backoff for reconnection
            logger.info(f"Reconnecting in {reconnect_delay} seconds...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

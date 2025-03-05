import json
import logging
import asyncio
import os
import uuid
from bot_logic.core.status import service_status
from bot_logic.services.redis_service import subscribe_to_channel, get_message, close_pubsub
from bot_logic.handlers.message_processor import process_message

logger = logging.getLogger(__name__)

# Generate a unique ID for this instance, use environment variable if available
INSTANCE_ID = os.environ.get("INSTANCE_NAME", str(uuid.uuid4())[:8])
logger.info(f"Message listener started with instance ID: {INSTANCE_ID}")

async def message_listener():
    """Listen for messages on Redis and process them."""
    reconnect_delay = 5  # Start with a short delay
    max_reconnect_delay = 60  # Maximum reconnect delay
    
    while True:  # Keep trying to reconnect
        pubsub = None
        
        try:
            # Subscribe to the messages channel
            pubsub = await subscribe_to_channel("messages")
            if not pubsub:
                logger.error(f"[Instance {INSTANCE_ID}] Failed to subscribe to messages channel")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
                continue
            
            # Reset reconnect delay on successful connection
            reconnect_delay = 5
            logger.info(f"[Instance {INSTANCE_ID}] Subscribed to messages channel")
            
            while True:
                try:
                    # Get message with short timeout
                    message = await get_message(pubsub, timeout=0.3)
                    
                    if message and message["type"] == "message":
                        logger.info(f"[Instance {INSTANCE_ID}] Received message from Redis")
                        try:
                            data = json.loads(message["data"])
                            logger.debug(f"[Instance {INSTANCE_ID}] Raw message data: {data}")
                            await process_message(data)
                        except json.JSONDecodeError:
                            logger.error(f"[Instance {INSTANCE_ID}] Invalid JSON received")
                            service_status.record_error("Invalid JSON format")
                        except Exception as e:
                            logger.error(f"[Instance {INSTANCE_ID}] Error processing message: {e}")
                            service_status.record_error(e)
                    
                    # Small delay to prevent CPU hogging
                    await asyncio.sleep(0.1)
                    
                except asyncio.CancelledError:
                    logger.info(f"[Instance {INSTANCE_ID}] Message listener loop cancelled")
                    raise
                except Exception as e:
                    logger.error(f"[Instance {INSTANCE_ID}] Error in Redis message loop: {e}")
                    service_status.record_error(e)
                    # Break inner loop to reconnect
                    break
                
        except asyncio.CancelledError:
            logger.info(f"[Instance {INSTANCE_ID}] Message listener task was cancelled")
            break
        except Exception as e:
            logger.error(f"[Instance {INSTANCE_ID}] Error in message listener: {e}")
            service_status.set_redis_status(False)
            service_status.record_error(e)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
        finally:
            # Clean up resources
            await close_pubsub(pubsub)
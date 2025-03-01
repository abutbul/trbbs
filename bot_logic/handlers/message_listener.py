import json
import logging
import asyncio
from bot_logic.core.status import service_status
from bot_logic.services.redis_service import subscribe_to_channel, get_message, close_pubsub
from bot_logic.handlers.message_processor import process_message

logger = logging.getLogger(__name__)

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
                logger.error("Failed to subscribe to messages channel")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
                continue
            
            # Reset reconnect delay on successful connection
            reconnect_delay = 5
            logger.info("Subscribed to messages channel")
            
            while True:
                try:
                    # Get message with short timeout
                    message = await get_message(pubsub, timeout=0.3)
                    
                    if message and message["type"] == "message":
                        logger.info(f"Received message from Redis: {message['data']}")
                        try:
                            data = json.loads(message["data"])
                            logger.info(f"Processing raw message: {message['data']}")
                            logger.info("Successfully parsed JSON message")
                            await process_message(data)
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON received: {message['data']}")
                            service_status.record_error("Invalid JSON format")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                            service_status.record_error(e)
                    
                    # Small delay to prevent CPU hogging
                    await asyncio.sleep(0.1)
                    
                except asyncio.CancelledError:
                    logger.info("Message listener loop cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in Redis message loop: {e}")
                    service_status.record_error(e)
                    # Break inner loop to reconnect
                    break
                
        except asyncio.CancelledError:
            logger.info("Message listener task was cancelled")
            break
        except Exception as e:
            logger.error(f"Error in message listener: {e}")
            service_status.set_redis_status(False)
            service_status.record_error(e)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
        finally:
            # Clean up resources
            await close_pubsub(pubsub)
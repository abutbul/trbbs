import json
import logging
import asyncio
import httpx
from bot_logic.services.redis_service import get_redis
from bot_logic.core.status import service_status

logger = logging.getLogger(__name__)

# Flag to track if handler is running
is_running = False
handler_task = None

async def send_telegram_reaction(bot_token, chat_id, message_id, reaction_data):
    """Send a reaction to a Telegram message using the Telegram API."""
    try:
        base_url = f"https://api.telegram.org/bot{bot_token}/setMessageReaction"
        
        # Prepare the payload according to Telegram API requirements
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": reaction_data.get("reaction", []),
            "is_big": False  # Standard size reactions
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(base_url, json=payload, timeout=10.0)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.debug(f"Successfully sent reaction to Telegram: {reaction_data}")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description')}")
                    return False
            else:
                logger.error(f"Telegram API returned status code {response.status_code}: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending Telegram reaction: {e}")
        service_status.record_error(e)
        return False

async def handle_reaction_message(message_data):
    """Process a reaction message based on platform type."""
    try:
        source_type = message_data.get("source_type")
        
        if source_type == "telegram":
            # Handle Telegram reactions
            bot_token = message_data.get("bot_token")
            chat_id = message_data.get("chat_id")
            message_id = message_data.get("message_id")
            
            if not all([bot_token, chat_id, message_id]):
                logger.error(f"Missing required fields for Telegram reaction: {message_data}")
                return False
            
            return await send_telegram_reaction(bot_token, chat_id, message_id, message_data)
        else:
            logger.warning(f"Unsupported platform for reactions: {source_type}")
            return False
    except Exception as e:
        logger.error(f"Error handling reaction message: {e}")
        service_status.record_error(e)
        return False

async def reaction_listener():
    """Listen for reaction messages from Redis pubsub."""
    global is_running
    
    logger.info("Starting reaction listener...")
    is_running = True
    
    try:
        redis = await get_redis()
        if not redis:
            logger.error("Failed to connect to Redis for reaction listener")
            is_running = False
            return
        
        # Create PubSub instance
        pubsub = redis.pubsub()
        
        # Subscribe to reaction channel
        await pubsub.subscribe("message_reactions")
        logger.info("Subscribed to message_reactions channel")
        
        # Process incoming messages
        while is_running:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                try:
                    # Parse the message data
                    if message["type"] == "message":
                        data = json.loads(message["data"])
                        logger.debug(f"Received reaction message: {data}")
                        await handle_reaction_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in reaction message: {message['data']}")
                except Exception as e:
                    logger.error(f"Error processing reaction message: {e}")
                    service_status.record_error(e)
            
            # Small sleep to prevent CPU overuse
            await asyncio.sleep(0.1)
        
        # Unsubscribe when stopping
        await pubsub.unsubscribe("message_reactions")
        logger.info("Unsubscribed from message_reactions channel")
    except Exception as e:
        logger.error(f"Error in reaction listener: {e}")
        service_status.record_error(e)
    finally:
        is_running = False
        logger.info("Reaction listener stopped")

async def start_reaction_handler():
    """Start the reaction handler service."""
    global handler_task, is_running
    
    if is_running:
        logger.warning("Reaction handler is already running")
        return
    
    handler_task = asyncio.create_task(reaction_listener())
    logger.info("Reaction handler started")

async def stop_reaction_handler():
    """Stop the reaction handler service."""
    global is_running, handler_task
    
    if not is_running:
        logger.debug("Reaction handler is not running")
        return
    
    is_running = False
    
    if handler_task:
        # Wait for the task to complete
        try:
            await asyncio.wait_for(handler_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout while waiting for reaction handler to stop")
        except Exception as e:
            logger.error(f"Error stopping reaction handler: {e}")
    
    logger.info("Reaction handler stopped")

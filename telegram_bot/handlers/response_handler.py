import json
import asyncio
import logging
import re
import time
import random
from telegram.error import TelegramError
from telegram_bot.core.status import service_status
from telegram_bot.services.redis_service import (
    subscribe_to_channel, 
    get_message, 
    close_pubsub
)
from telegram_bot.services.telegram_service import send_message_with_token

logger = logging.getLogger(__name__)

# Track rate limit retries with exponential backoff
retry_delays = {}  # user_id -> (next_retry_time, retry_count)
MAX_RETRY_COUNT = 5  # Maximum number of retries
BASE_RETRY_DELAY = 2  # Base delay in seconds for exponential backoff

async def process_response_message(data):
    """Process a response message."""
    try:
        response_data = json.loads(data)
        
        # Only process telegram responses
        if response_data.get("source_type") == "telegram":
            user_id = int(response_data["source_id"])
            content = response_data["content"]
            
            # Get the bot token from the response data
            bot_token = response_data.get("bot_token")
            
            # Get the chat ID and type from the response data
            chat_id = response_data.get("chat_id", str(user_id))
            chat_type = response_data.get("chat_type", "dm")
            
            # Convert chat_id to int
            chat_id = int(chat_id)
            
            if not bot_token:
                logger.error(f"No bot token in response data for user {user_id}")
                return
            
            logger.info(f"Sending response to Telegram {chat_type} {chat_id}: {content[:50]}...")
            
            # Send message back to the appropriate chat (channel or user DM)
            success = await send_message_with_token(bot_token, chat_id, content)
            if success:
                logger.info(f"Successfully sent response to {chat_type} {chat_id}")
            else:
                logger.error(f"Failed to send response to {chat_type} {chat_id}")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing response: {error_msg}")
        service_status.record_error(e)

async def response_listener():
    """Listen for responses on Redis and send them back to Telegram users."""
    reconnect_delay = 5  # Start with a short delay
    max_reconnect_delay = 60  # Maximum reconnect delay
    
    while True:  # Keep trying to reconnect
        pubsub = None
        
        try:
            # Subscribe to the responses channel
            pubsub = await subscribe_to_channel("responses")
            if not pubsub:
                logger.error("Failed to subscribe to responses channel")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
                continue
            
            # Reset reconnect delay on successful connection
            reconnect_delay = 5
            logger.info("Listening for responses on Redis 'responses' channel")
            
            while True:
                try:
                    # Simple polling loop - get message with short timeout
                    message = await get_message(pubsub, timeout=1.0)
                    
                    if message and message["type"] == "message":
                        # Process each message directly and sequentially for simplicity
                        await process_response_message(message["data"])
                        
                except asyncio.CancelledError:
                    logger.info("Response listener loop cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in Redis message loop: {e}")
                    service_status.record_error(e)
                    # Break inner loop to reconnect
                    break
                
                # Short sleep to prevent CPU hammering
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.info("Response listener task was cancelled")
            break
        except Exception as e:
            logger.error(f"Error in response listener: {e}")
            service_status.set_redis_status(False)
            service_status.record_error(e)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
        finally:
            # Clean up resources
            await close_pubsub(pubsub)
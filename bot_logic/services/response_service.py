import json
import logging
import asyncio
from bot_logic.core.status import service_status
from bot_logic.services.redis_service import get_redis, publish_message

logger = logging.getLogger(__name__)

async def send_response(source_type, source_id, content, original_message):
    """Send a response back to the user."""
    try:
        # Create response data with original message's bot_token
        response_data = {
            "source_type": source_type,
            "source_id": source_id,
            "content": content,
            # Include the bot token from the original message
            "bot_token": original_message.get("bot_token"),
            # Include chat_id and chat_type for proper response routing
            "chat_id": original_message.get("chat_id", source_id),
            "chat_type": original_message.get("chat_type", "dm"),
            # Add message_id for reply functionality
            "reply_to_message_id": original_message.get("message_id"),
            # Include response mode from rule if available, default to "new_message"
            "response_mode": original_message.get("response_mode", "new_message")
        }
        
        # Publish to responses channel
        success = await publish_message("responses", response_data)
        
        if success:
            logger.info(f"Publishing response to Redis: {json.dumps(response_data)[:100]}...")
            logger.info(f"Sent response to {source_type} ({response_data['chat_id']} - {response_data['chat_type']}): {content[:100]}...")
            service_status.increment_responses()
            return True
        else:
            logger.error("Failed to publish response to Redis")
            return False
    except Exception as e:
        logger.error(f"Error sending response: {e}")
        service_status.record_error(e)
        return False
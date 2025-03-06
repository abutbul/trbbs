import json
import logging
from bot_logic.core.status import service_status
from bot_logic.services.redis_service import get_redis, publish_message

logger = logging.getLogger(__name__)

# Emoji constants - using emoji from Telegram's allowed reaction list
PROCESSING_EMOJI = "🤔"  # Thinking emoji for "processing"
COMPLETED_EMOJI = "💯"   # 100 emoji for "completed"
ERROR_EMOJI = "😡"       # Angry emoji for errors

# Full list of permitted Telegram reaction emoji for reference
TELEGRAM_ALLOWED_REACTIONS = [
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", 
    "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", 
    "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", 
    "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍", 
    "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", 
    "💊", "🙊", "😎", "👾", "🤷‍♂", "🤷", "🤷‍♀", "😡"
]

async def add_reaction(source_type, message_id, emoji, bot_token, chat_id):
    """Add a reaction emoji to a message."""
    try:
        # Verify emoji is in allowed list for Telegram
        if source_type == "telegram" and emoji not in TELEGRAM_ALLOWED_REACTIONS:
            logger.warning(f"Emoji {emoji} not in Telegram allowed reactions list, using 👍 instead")
            emoji = "👍"  # Default to thumbs up if invalid
        
        # Make sure message_id is a string
        message_id = str(message_id) if message_id is not None else None
        
        # Validate message_id
        if not message_id:
            logger.error("Cannot add reaction: message_id is empty")
            return False
        
        # Create properly formatted reaction data following Telegram API specs
        if source_type == "telegram":
            # Create reaction in Telegram-specific format with proper reaction structure
            reaction_data = {
                "source_type": source_type,
                "message_id": message_id,
                "reaction": [{  # This is the key change - an array of reaction objects
                    "type": "emoji",  # Type field is required
                    "emoji": emoji    # The emoji itself
                }],
                "action": "add",
                "bot_token": bot_token,
                "chat_id": chat_id
            }
        else:
            # For non-Telegram platforms, use the original format
            reaction_data = {
                "source_type": source_type,
                "message_id": message_id,
                "emoji": emoji,
                "action": "add",
                "bot_token": bot_token,
                "chat_id": chat_id
            }
        
        # Check if we have any subscribers before publishing
        redis = await get_redis()
        if redis:
            subscribers = await redis.pubsub_numsub("message_reactions")
            sub_count = subscribers[0][1] if subscribers and len(subscribers) > 0 else 0
            
            if sub_count == 0:
                logger.warning("No subscribers to message_reactions channel! Reactions will be lost.")
                # Try to directly send a message to help debug
                await redis.set(f"debug:reaction:{message_id}", json.dumps(reaction_data), ex=60)
                logger.info(f"Saved reaction data to Redis key debug:reaction:{message_id} for debugging")
        
        # Log the complete reaction data for debugging
        logger.debug(f"Publishing reaction data: {reaction_data}")
        
        # Publish to reactions channel
        success = await publish_message("message_reactions", reaction_data)
        
        if success:
            logger.info(f"Added reaction {emoji} to message {message_id}")
            return True
        else:
            logger.error(f"Failed to publish reaction {emoji}")
            return False
    except Exception as e:
        logger.error(f"Error adding reaction: {e}")
        service_status.record_error(e)
        return False

async def remove_reaction(source_type, message_id, emoji, bot_token, chat_id):
    """Remove a reaction emoji from a message."""
    try:
        # Create reaction data in proper format for the platform
        if source_type == "telegram":
            # For Telegram, use an empty array to remove all reactions
            reaction_data = {
                "source_type": source_type,
                "message_id": message_id,
                "reaction": [],  # Empty array to clear reactions
                "action": "remove",
                "bot_token": bot_token,
                "chat_id": chat_id
            }
        else:
            # For other platforms, use the original format
            reaction_data = {
                "source_type": source_type,
                "message_id": message_id,
                "emoji": emoji,
                "action": "remove",
                "bot_token": bot_token,
                "chat_id": chat_id
            }
        
        # Publish to reactions channel
        success = await publish_message("message_reactions", reaction_data)
        
        if success:
            logger.info(f"Removed reaction(s) from message {message_id}")
            return True
        else:
            logger.error(f"Failed to publish reaction removal")
            return False
    except Exception as e:
        logger.error(f"Error removing reaction: {e}")
        service_status.record_error(e)
        return False

async def update_reaction(source_type, message_id, old_emoji, new_emoji, bot_token, chat_id):
    """Update a reaction emoji on a message."""
    try:
        # Remove old emoji first
        remove_result = await remove_reaction(source_type, message_id, old_emoji, bot_token, chat_id)
        
        # Add new emoji
        add_result = await add_reaction(source_type, message_id, new_emoji, bot_token, chat_id)
        
        logger.info(f"Updated reaction from {old_emoji} to {new_emoji} on message {message_id}")
        return remove_result and add_result
    except Exception as e:
        logger.error(f"Error updating reaction: {e}")
        service_status.record_error(e)
        return False

async def add_processing_reaction(source_type, message_id, bot_token, chat_id):
    """Add the processing emoji to a message."""
    return await add_reaction(source_type, message_id, PROCESSING_EMOJI, bot_token, chat_id)

async def update_to_completed_reaction(source_type, message_id, bot_token, chat_id):
    """Update from processing emoji to completed emoji."""
    return await update_reaction(source_type, message_id, PROCESSING_EMOJI, COMPLETED_EMOJI, bot_token, chat_id)

async def add_error_reaction(source_type, message_id, bot_token, chat_id):
    """Add error emoji to a message."""
    return await add_reaction(source_type, message_id, ERROR_EMOJI, bot_token, chat_id)

"""
This module handles message reactions (emoji) for Telegram messages.
You'll need to implement this part based on your Telegram API integration.

The main functionality needed is:
1. Subscribe to the "message_reactions" Redis channel
2. Process incoming reaction commands (add/remove emoji)
3. Use Telegram Bot API to apply these reactions

Sample reaction data format from Redis:
{
    "source_type": "telegram",
    "message_id": "12345",
    "emoji": "👋",
    "action": "add",  # or "remove"
    "bot_token": "bot_token_here",
    "chat_id": "chat_id_here"
}
"""
import json
import logging
import asyncio
from telegram import Bot
from telegram.error import TelegramError, BadRequest
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

async def handle_reaction(reaction_data):
    """Handle a reaction request from Redis."""
    try:
        # Log full reaction data for debugging
        logger.debug(f"Handling reaction: {json.dumps(reaction_data)}")
        
        # Extract data
        source_type = reaction_data.get("source_type")
        if source_type != "telegram":
            logger.warning(f"Ignoring non-Telegram reaction: {source_type}")
            return False
            
        message_id = reaction_data.get("message_id")
        action = reaction_data.get("action")
        bot_token = reaction_data.get("bot_token")
        chat_id = reaction_data.get("chat_id")
        
        # Get reactions in proper format
        # If using new format, it will be in "reaction" field
        # If using old format, it will be in "emoji" field
        reactions = reaction_data.get("reaction")
        if not reactions and "emoji" in reaction_data:
            # Convert old format to new format
            emoji = reaction_data.get("emoji")
            if emoji:
                reactions = [{"type": "emoji", "emoji": emoji}]
        
        # Check for required fields
        if not all([message_id, action, bot_token, chat_id]):
            logger.error(f"Missing required fields in reaction data")
            return False
            
        # For "add" action, make sure we have reactions
        if action == "add" and not reactions:
            logger.error("Missing reactions for add action")
            return False
        
        # Convert IDs to integers for Telegram API
        try:
            # Make sure message_id is an integer
            if isinstance(message_id, str):
                # If it contains non-numeric characters, try to extract the numeric part
                if not message_id.isdigit():
                    import re
                    match = re.search(r'(\d+)', message_id)
                    if match:
                        message_id = int(match.group(1))
                    else:
                        logger.error(f"Cannot convert message_id to integer: {message_id}")
                        return False
                else:
                    message_id = int(message_id)
            
            # Make sure chat_id is an integer
            if isinstance(chat_id, str) and chat_id.isdigit():
                chat_id = int(chat_id)
        except (ValueError, TypeError) as e:
            logger.error(f"Error converting IDs to integers: {e}")
            return False
        
        logger.info(f"Processing reaction for message {message_id} in chat {chat_id}")
        
        # Create bot instance
        bot = Bot(token=bot_token)
        
        if action == "add":
            # Add reaction to message
            try:
                logger.info(f"Adding reaction to message {message_id}")
                
                # Use the Telegram API with proper reaction format
                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=message_id,
                    reaction=reactions  # Pass the reaction array directly
                )
                logger.info("Successfully added reaction")
                return True
                
            except BadRequest as e:
                logger.error(f"Telegram API error: {e}")
                
                # If the specific reaction is invalid, try a fallback
                if "REACTION_INVALID" in str(e) or "not allowed" in str(e).lower():
                    try:
                        # Try with a simple thumbs up reaction
                        await bot.set_message_reaction(
                            chat_id=chat_id,
                            message_id=message_id,
                            reaction=[{"type": "emoji", "emoji": "👍"}]
                        )
                        logger.info("Used fallback reaction 👍")
                        return True
                    except Exception as e2:
                        logger.error(f"Fallback reaction failed: {e2}")
                
                return False
                
            except TelegramError as e:
                logger.error(f"Telegram error: {e}")
                return False
            
        elif action == "remove":
            # Remove reaction from message
            try:
                logger.info(f"Removing reactions from message {message_id}")
                
                # To remove all reactions in Telegram, pass an empty array
                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=message_id,
                    reaction=[]
                )
                logger.info("Successfully removed reactions")
                return True
                
            except TelegramError as e:
                logger.error(f"Telegram error removing reaction: {e}")
                return False
            
        else:
            logger.error(f"Unknown reaction action: {action}")
            return False
            
    except Exception as e:
        logger.error(f"Error handling reaction: {e}")
        return False

import json
import time
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackContext
from telegram_bot.core.status import service_status
from telegram_bot.services.redis_service import publish_message
from telegram_bot.services.telegram_service import safe_telegram_reply

logger = logging.getLogger(__name__)

async def handle_message(update: Update, context: CallbackContext = None, bot_token: str = None) -> None:
    """Forward all messages to Redis for processing."""
    user = update.effective_user
    message_text = update.message.text
    
    logger.info(f"Received message from {user.first_name} (ID: {user.id}): {message_text}")
    service_status.increment_messages()
    
    # Process in background
    asyncio.create_task(process_user_message(update, message_text, bot_token))

async def process_user_message(update: Update, message_text: str, bot_token: str = None):
    """Process user message in background."""
    
    # Determine if message is from a channel/group or direct message
    chat_type = "channel" if update.effective_chat and update.effective_chat.type in ["group", "supergroup", "channel"] else "dm"
    
    message_data = {
        "source_type": "telegram",
        "source_id": str(update.effective_user.id),
        "content": message_text,
        "username": update.effective_user.username or update.effective_user.first_name,
        "message_id": str(update.message.message_id),
        "timestamp": time.time(),
        "chat_type": chat_type,
        # Add chat ID to track where the message came from
        "chat_id": str(update.effective_chat.id) if update.effective_chat else str(update.effective_user.id)
    }
    
    # Add bot token information if available
    if bot_token:
        message_data["bot_token"] = bot_token
    
    try:
        # Publish message to Redis for asynchronous processing
        success = await publish_message("messages", message_data)
        if success:
            logger.info(f"Published message to Redis: {message_data}")
        else:
            await safe_telegram_reply(update, "Sorry, I couldn't process your message.")
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        service_status.record_error(e)
        await safe_telegram_reply(update, "Sorry, I couldn't process your message.")

async def process_single_update(update, bot_token=None):
    """Process a single update in a background task."""
    try:
        # Process the update directly through the message handler
        if update.message and update.message.text:
            # Process the message with the bot token
            await handle_message(update, None, bot_token)
            return True
        else:
            logger.info(f"Skipping non-text update {update.update_id}")
            return False
    except Exception as e:
        logger.error(f"Error processing update {update.update_id}: {e}")
        service_status.record_error(e)
        # Try to respond to the user if possible
        try:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, I couldn't process your message properly."
                )
        except Exception:
            pass
        return False

async def error_handler(update, context):
    """Handle errors in the telegram bot."""
    logger.error(f"Update {update} caused error: {context.error}")
    service_status.record_error(context.error)

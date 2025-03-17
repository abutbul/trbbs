import logging
import asyncio
import time
import json
import os
from typing import List, Optional, Dict, Any, Tuple
from telegram import Bot, Update
from telegram.error import TelegramError, Conflict
from telegram_bot.core.config import (
    TELEGRAM_BOT_TOKEN, 
    BOT_CONFIG_PATH,
    load_bot_config
)
from telegram_bot.core.status import service_status

logger = logging.getLogger(__name__)

# Dictionary to store bot instances by token
bot_instances = {}
# Define bot_lock in the global scope
bot_lock = asyncio.Lock()
# Dictionary to store locks for each bot token to prevent conflicts
token_locks = {}
last_update_attempt = 0
updates_in_progress = False

# Get list of bot tokens from config
def get_bot_tokens():
    """Get list of active bot tokens from config."""
    config = load_bot_config()
    tokens = []
    
    for bot in config.get('bots', []):
        if bot.get('enabled', True) and bot.get('token'):
            tokens.append((bot.get('token'), bot.get('bot_name', 'unnamed')))
    
    if not tokens and TELEGRAM_BOT_TOKEN:
        # Fallback to environment variable if no configured bots
        tokens = [(TELEGRAM_BOT_TOKEN, 'default')]
    
    return tokens

async def get_telegram_bot(token=None):
    """Get or create a bot instance for the specified token."""
    global bot_instances
    
    if token is None:
        token = TELEGRAM_BOT_TOKEN
    
    # Create bot instance if it doesn't exist
    if token not in bot_instances:
        try:
            logger.info(f"Creating new Bot instance for token ending in ...{token[-5:]}")
            bot_instances[token] = Bot(token=token)
            # Verify the token is valid
            me = await bot_instances[token].get_me()
            logger.info(f"Connected to bot @{me.username} (ID: {me.id})")
        except Exception as e:
            logger.error(f"Error creating Telegram bot for token ending in ...{token[-5:]}: {e}")
            raise
    
    return bot_instances[token]

async def initialize_bots():
    """Initialize all configured Telegram bots."""
    tokens = get_bot_tokens()
    logger.info(f"Initializing {len(tokens)} Telegram bots...")
    
    # Initialize each bot with some delay between them
    for token, name in tokens:
        try:
            await initialize_bot(token, name)
            # Add small delay between bot initialization to avoid rate limits
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to initialize bot {name}: {e}")
    
    # Mark bots as connected if at least one was successful
    service_status.set_telegram_status(len(bot_instances) > 0)
    logger.info(f"Initialized {len(bot_instances)} bot instances successfully")
    return len(bot_instances) > 0

async def initialize_bot(token, name):
    """Initialize a specific Telegram bot."""
    try:
        async with bot_lock:
            # Remove this bot instance if it exists already
            if token in bot_instances:
                logger.info(f"Closing existing bot instance for {name}")
                del bot_instances[token]
            
            # Create a temporary bot instance to get webhook info
            temp_bot = Bot(token=token)
            webhook_info = await temp_bot.get_webhook_info()
            logger.info(f"Bot {name} webhook status: {webhook_info.url or 'No webhook'}")
            
            if webhook_info.url:
                logger.info(f"Removing existing webhook for bot {name}...")
                await temp_bot.delete_webhook()
                logger.info(f"Webhook removed for bot {name}")
                # Wait a bit for Telegram to fully clear the webhook
                await asyncio.sleep(1)
            
            # Find pending updates
            try:
                updates = await temp_bot.get_updates(offset=0, limit=1, timeout=1)
                logger.info(f"Found {len(updates)} pending updates for bot {name}")
                
                if updates:
                    logger.info(f"Clearing pending updates for bot {name}...")
                    # Get the highest update ID to mark all as read
                    highest_id = updates[-1].update_id
                    await temp_bot.get_updates(offset=highest_id + 1, timeout=1)
                    logger.info(f"Cleared updates up to ID {highest_id} for bot {name}")
            except Exception as e:
                # If there's a conflict, wait longer before trying again
                if "Conflict" in str(e):
                    logger.warning(f"Conflict detected for bot {name}, waiting for other sessions to expire...")
                    await asyncio.sleep(10)
                    # Try again to get updates with a new bot instance
                    temp_bot = Bot(token=token)
                    # Just mark as processed without actually getting updates
                    await temp_bot.get_updates(offset=-1, limit=1, timeout=1)
                else:
                    logger.error(f"Error getting updates for bot {name}: {e}")
            
            # Wait for any existing sessions to expire
            logger.info(f"Waiting for any existing sessions to expire for bot {name}...")
            await asyncio.sleep(3)
            
            # Store the bot in our instances dictionary
            bot_instances[token] = temp_bot
            
            logger.info(f"Bot {name} initialized successfully")
            return True
    
    except Exception as e:
        logger.error(f"Failed to initialize bot {name}: {e}")
        service_status.record_error(e)
        return False

async def get_updates_for_bot(token, name, offset=None, limit=100, timeout=30) -> Tuple[List[Update], str]:
    """Get updates for a specific bot token."""
    # Get or create a lock for this specific token
    if token not in token_locks:
        token_locks[token] = asyncio.Lock()
    
    # Use the token-specific lock to prevent conflicts
    if token_locks[token].locked():
        logger.debug(f"Update retrieval for bot {name} already in progress, skipping")
        return [], token
    
    try:
        # Acquire lock for this specific token
        async with token_locks[token]:
            logger.debug(f"Getting updates for bot {name} with offset {offset}")
            try:
                # Get the bot instance
                bot = await get_telegram_bot(token)
                
                # Use a shorter timeout for better responsiveness
                actual_timeout = min(5, timeout)
                
                # Try to get updates
                updates = await bot.get_updates(offset=offset, limit=limit, timeout=actual_timeout)
                
                if updates:
                    logger.info(f"Received {len(updates)} updates for bot {name}")
                
                return updates, token
                
            except Conflict as e:
                logger.warning(f"Conflict detected for bot {name}, reinitializing: {e}")
                # Clear the bot instance and try to reinitialize
                if token in bot_instances:
                    del bot_instances[token]
                await asyncio.sleep(2)  # Wait before trying to reinitialize
                await initialize_bot(token, name)
                return [], token
                
            except TelegramError as e:
                logger.error(f"Telegram API error when getting updates for bot {name}: {e}")
                # Don't try to reinitialize here to avoid cascading errors
                return [], token
                
            except Exception as e:
                logger.error(f"Unexpected error getting updates for bot {name}: {e}")
                return [], token
    
    except asyncio.CancelledError:
        logger.warning(f"Get updates operation cancelled for bot {name}")
        raise
    except Exception as e:
        logger.error(f"Error acquiring lock for bot {name}: {e}")
        return [], token

async def get_updates(offset=None, limit=100, timeout=30) -> List[Update]:
    """Get updates from all configured bots."""
    tokens = get_bot_tokens()
    if not tokens:
        logger.warning("No bot tokens configured")
        return []
    
    # Only use the first token for now
    token, name = tokens[0]
    updates, _ = await get_updates_for_bot(token, name, offset, limit, timeout)
    return updates

async def poll_all_bots(last_update_ids=None):
    """Poll for updates from all configured bots."""
    if last_update_ids is None:
        last_update_ids = {}
    
    tokens = get_bot_tokens()
    all_updates = []
    
    # Poll each bot with a small delay between them
    for i, (token, name) in enumerate(tokens):
        try:
            # Add a small stagger between bots to reduce conflicts
            if i > 0:
                await asyncio.sleep(1)
                
            offset = last_update_ids.get(token, 0) + 1 if token in last_update_ids else None
            updates, bot_token = await get_updates_for_bot(token, name, offset, 100, 5)
            
            if updates:
                # Update the last ID for this bot
                last_update_ids[token] = updates[-1].update_id
                all_updates.extend([(update, token, name) for update in updates])
        except Exception as e:
            logger.error(f"Error polling bot {name}: {e}")
    
    return all_updates, last_update_ids

async def send_message(chat_id: int, text: str, token=None, **kwargs) -> bool:
    """Send a message to a Telegram chat with error handling."""
    tokens = get_bot_tokens() if token is None else [(token, "specified")]
    
    if not tokens:
        logger.error("No tokens available to send message")
        return False
    
    # Try with the specified token or the first available one
    token, name = tokens[0]
    
    try:
        bot = await get_telegram_bot(token)
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except Exception as e:
        logger.error(f"Error sending message to {chat_id} using bot {name}: {e}")
        return False

async def send_message_with_token(bot_token: str, user_id: int, text: str) -> bool:
    """Send a message using a specific bot token."""
    try:
        # Create a new bot instance each time for reliability
        bot = Bot(token=bot_token)
        
        # Send the message
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='HTML'
        )
        return True
    except TelegramError as e:
        logger.error(f"Telegram error sending message to {user_id}: {e}")
        service_status.record_error(e)
        return False
    except Exception as e:
        logger.error(f"Error sending message to {user_id}: {e}")
        service_status.record_error(e)
        return False

async def safe_telegram_reply(update: Update, text: str, token=None, **kwargs) -> bool:
    """Safely reply to a Telegram message."""
    try:
        if update.effective_message:
            await update.effective_message.reply_text(text, **kwargs)
            return True
    except Exception as e:
        logger.error(f"Error replying to message: {e}")
    return False

async def shutdown_bots():
    """Shut down all Telegram bots."""
    global bot_instances
    
    logger.info("Shutting down Telegram bots...")
    bot_instances = {}
    service_status.set_telegram_status(False)
    logger.info("All Telegram bots shut down")

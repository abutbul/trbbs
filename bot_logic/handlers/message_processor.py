import os
import json
import logging
import subprocess
import httpx  # Add this import
from bot_logic.core.config import load_bot_config
from bot_logic.core.status import service_status
from bot_logic.handlers.rule_matcher import ensure_bot_usernames, find_all_matching_bot_rules, get_available_commands
from bot_logic.services.response_service import send_response
from bot_logic.services.api_service import send_chat_message  # Add this import
import uuid
import asyncio
from bot_logic.services.redis_service import try_lock_user, release_user_lock, try_claim_message

logger = logging.getLogger(__name__)

# Generate a unique ID for this bot-logic instance
INSTANCE_ID = os.environ.get("INSTANCE_NAME", str(uuid.uuid4())[:8])
logger.info(f"Bot-logic instance started with ID: {INSTANCE_ID}")

async def process_message(message_data):
    """Process an incoming message and generate a response."""
    try:
        # Create a unique message identifier
        message_id = _extract_message_id(message_data)
        
        if not message_id:
            logger.warning("Couldn't extract message ID, skipping message")
            return
        
        # Try to claim this message for processing
        claim_acquired = await try_claim_message(message_id, INSTANCE_ID)
        
        if not claim_acquired:
            logger.info(f"Message {message_id} is already being processed by another instance, skipping")
            return
            
        # Extract user identification for user-level locking
        user_id = _extract_user_id(message_data)
        
        if not user_id:
            logger.warning("Couldn't extract user ID from message, processing without user lock")
            await _process_message_internal(message_data)
            return
            
        # Try to acquire lock for this user
        lock_acquired = await try_lock_user(user_id, INSTANCE_ID)
        
        if not lock_acquired:
            logger.info(f"User {user_id} is being processed by another instance, will retry later")
            # We'll skip for now - the message claim ensures it won't be lost
            return
            
        try:
            # Process the message with lock protection
            await _process_message_internal(message_data)
        finally:
            # Always try to release the lock when done
            await release_user_lock(user_id, INSTANCE_ID)
            
    except Exception as e:
        logger.error(f"Error in process_message: {e}")
        service_status.record_error(e)

def _extract_message_id(message):
    """Extract a unique message identifier."""
    source_type = message.get('source_type', 'unknown')
    message_id = message.get('message_id')
    timestamp = message.get('timestamp', '')
    
    if message_id:
        return f"{source_type}:{message_id}:{timestamp}"
    return None

def _extract_user_id(message):
    """Extract a unique user identifier from the message."""
    # Use the most specific identifier available
    if message.get("from_id"):
        return f"{message.get('source_type')}:{message.get('from_id')}"
    elif message.get("chat_id"):
        return f"{message.get('source_type')}:{message.get('chat_id')}"
    return None

async def _process_message_internal(message_data):
    """Process the message after lock has been acquired."""
    try:
        message_text = message_data.get("content", "")
        source_type = message_data.get("source_type", "")
        source_id = message_data.get("source_id", "")
        bot_token = message_data.get("bot_token", "")
        
        # Determine chat context (dm or channel)
        chat_type = message_data.get("chat_type", "dm")  # Default to dm for backward compatibility
        # Get the chat_id where the message originated
        chat_id = message_data.get("chat_id", source_id)
        
        logger.info(f"Processing message: '{message_text}' from {source_type}:{source_id} in chat {chat_id} via bot token ending ...{bot_token[-5:] if bot_token else 'none'} in context: {chat_type}")
        
        # Update status
        service_status.increment_messages()
        
        # Load bot configuration
        config = await load_bot_config()
        
        # First, make sure bot usernames are available in the config for @botname matching
        await ensure_bot_usernames(config)
        
        # Find ALL matching bot rules
        matches = await find_all_matching_bot_rules(message_text, config, bot_token, chat_type)
        
        if matches:
            # Process all matching rules
            await process_matching_rules(matches, source_type, source_id, chat_id, chat_type)
        else:
            # No rule matched, but we know which bot received the message
            # Generate a default helpful response
            await handle_no_matches(bot_token, config, source_type, source_id, chat_id, chat_type)
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        service_status.record_error(e)

async def process_matching_rules(matches, source_type, source_id, chat_id, chat_type):
    """Process all matching rules and generate responses."""
    for bot, rule in matches:
        response_type = rule.get("response_type", "")
        response_content = rule.get("response_content", "")
        
        # Get the correct token to respond with
        response_token = bot.get("token")
        bot_name = bot.get("bot_name", "unnamed")
        
        logger.info(f"Generating response from bot {bot_name} with token ending ...{response_token[-5:] if response_token else 'none'}")
        
        if response_type == "message":
            # Simple text response - include chat_id and chat_type
            await send_response(source_type, source_id, response_content, {
                "bot_token": response_token, 
                "chat_id": chat_id,
                "chat_type": chat_type
            })
        elif response_type == "script":
            # Execute script and return output
            # Pass the original message for argument extraction
            original_message = rule.get("original_message", "")
            await execute_script_response(response_content, source_type, source_id, response_token, chat_id, chat_type, original_message)
        elif response_type == "api-chat":
            # New type: API chat response
            # Use the original message for processing
            original_message = rule.get("original_message", "")
            await execute_api_chat_response(original_message, source_type, source_id, response_token, chat_id, chat_type)
        else:
            logger.error(f"Unknown response type: {response_type}")

async def execute_script_response(script_command, source_type, source_id, response_token, chat_id, chat_type, original_message=""):
    """Execute a script and send its output as a response."""
    try:
        # Extract command arguments from the original message
        command_args = extract_command_args(original_message)
        
        # Append extracted arguments to the script command
        if command_args:
            full_command = f"{script_command} {command_args}"
        else:
            full_command = script_command
            
        logger.info(f"Executing script: {full_command}")
        
        # Execute the script with arguments and capture the output
        script_output = subprocess.check_output(full_command, shell=True, text=True)
        script_response = f"Output from script: {script_output}"
    except subprocess.CalledProcessError as e:
        script_response = f"Error executing script: {e}"
        service_status.record_error(e)
    
    await send_response(source_type, source_id, script_response, {
        "bot_token": response_token,
        "chat_id": chat_id,
        "chat_type": chat_type
    })

def extract_command_args(message):
    """Extract command arguments from a message.
    For example, from "/car 39438", extract "39438".
    """
    if not message:
        return ""
        
    # Split by whitespace and remove empty items
    parts = [part for part in message.strip().split() if part]
    
    if len(parts) <= 1:
        return ""  # No arguments provided
        
    # Return everything after the command
    return " ".join(parts[1:])

async def execute_api_chat_response(message_content, source_type, source_id, response_token, chat_id, chat_type):
    """Send message to API chat service and return the response."""
    try:
        # Extract the message content (everything after "bot:")
        if message_content.lower().startswith("bot:"):
            query = message_content[4:].strip()  # Remove 'bot:' and trim spaces
        else:
            query = message_content.strip()
            
        # Log the query being sent to the API
        logger.info(f"Sending request to API chat: {query[:100]}...")
        
        # Use the API service without sending an interim message
        success, response, error = await send_chat_message(query)
        
        if success and response:
            api_response = response
        else:
            api_response = f"Error communicating with API chat service: {error}"
            logger.error(f"API chat error: {error}")
    except Exception as e:
        api_response = f"Error communicating with API chat service: {e}"
        logger.error(f"API chat error: {e}")
        service_status.record_error(e)
    
    # Send the response
    await send_response(source_type, source_id, api_response, {
        "bot_token": response_token,
        "chat_id": chat_id,
        "chat_type": chat_type
    })

async def handle_no_matches(bot_token, config, source_type, source_id, chat_id, chat_type):
    """Handle the case when no rules match the message."""
    if bot_token:
        # Find which bot this token belongs to and get available commands
        bot_name, available_commands = await get_available_commands(bot_token, config)
        
        # Create a helpful response
        if available_commands:
            help_message = f"I don't understand that command. Available commands for {bot_name}:\n"
            help_message += "\n".join(available_commands)
            await send_response(source_type, source_id, help_message, {
                "bot_token": bot_token,
                "chat_id": chat_id,
                "chat_type": chat_type
            })
            logger.info(f"Sent default help message listing available commands")
        else:
            # Only respond with "don't understand" message in DMs, not in channels
            if chat_type.lower() == "dm" or chat_type.lower() == "private":
                await send_response(source_type, source_id, f"Sorry, I don't understand that command.", {
                    "bot_token": bot_token,
                    "chat_id": chat_id,
                    "chat_type": chat_type
                })
                logger.info(f"Sent generic 'don't understand' message")
            else:
                logger.info(f"Ignoring unrecognized command in {chat_type}")
    else:
        logger.info(f"No matching rule found and no bot token to generate default response")
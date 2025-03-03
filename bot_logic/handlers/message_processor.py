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

logger = logging.getLogger(__name__)

async def process_message(message_data):
    """Process an incoming message and generate a response."""
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
            await execute_script_response(response_content, source_type, source_id, response_token, chat_id, chat_type)
        elif response_type == "api-chat":
            # New type: API chat response
            # Use the original message for processing
            original_message = rule.get("original_message", "")
            await execute_api_chat_response(original_message, source_type, source_id, response_token, chat_id, chat_type)
        else:
            logger.error(f"Unknown response type: {response_type}")

async def execute_script_response(script_command, source_type, source_id, response_token, chat_id, chat_type):
    """Execute a script and send its output as a response."""
    try:
        # Execute the script and capture the output
        script_output = subprocess.check_output(script_command, shell=True, text=True)
        script_response = f"Output from script: {script_output}"
    except subprocess.CalledProcessError as e:
        script_response = f"Error executing script: {e}"
        service_status.record_error(e)
    
    await send_response(source_type, source_id, script_response, {
        "bot_token": response_token,
        "chat_id": chat_id,
        "chat_type": chat_type
    })

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
            await send_response(source_type, source_id, f"Sorry, I don't understand that command.", {
                "bot_token": bot_token,
                "chat_id": chat_id,
                "chat_type": chat_type
            })
            logger.info(f"Sent generic 'don't understand' message")
    else:
        logger.info(f"No matching rule found and no bot token to generate default response")
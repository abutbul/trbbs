import os
import json
import logging
import subprocess
import httpx
from bot_logic.core.config import load_bot_config
from bot_logic.core.status import service_status
from bot_logic.handlers.rule_matcher import ensure_bot_usernames, find_all_matching_bot_rules, get_available_commands, extract_numeric_id
from bot_logic.services.response_service import send_response
from bot_logic.services.api_service import send_chat_message
from bot_logic.services.reaction_service import add_processing_reaction, update_to_completed_reaction, add_error_reaction
import uuid
import asyncio
from bot_logic.services.redis_service import (
    try_lock_user, release_user_lock, try_claim_message, 
    store_active_command, get_active_command, queue_message,
    get_queued_messages, remove_from_queue
)
from bot_logic.services.chat_api_queue import enqueue_chat_request, get_queue_position

logger = logging.getLogger(__name__)

# Generate a unique ID for this bot-logic instance
INSTANCE_ID = os.environ.get("INSTANCE_NAME", str(uuid.uuid4())[:8])
logger.info(f"Bot-logic instance started with ID: {INSTANCE_ID}")

# Track active requests to properly handle reactions for consecutive commands
_active_requests = {}

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
            # User is being processed by another instance
            # Check if this message is the same as the active command
            active_cmd = await get_active_command(user_id)
            current_content = message_data.get("content", "").strip()
            
            if active_cmd and active_cmd.get("content") == current_content:
                # This is a duplicate command, ignore it
                logger.info(f"Duplicate command from user {user_id}, ignoring: {current_content[:50]}...")
                return
            else:
                # This is a different command, queue it for later processing
                logger.info(f"User {user_id} is busy, queuing different command: {current_content[:50]}...")
                await queue_message(user_id, message_data)
                return
            
        try:
            # Store this as the active command for the user
            await store_active_command(user_id, INSTANCE_ID, message_data)
            
            # Process the message with lock protection
            await _process_message_internal(message_data)
            
            # After processing current message, check if there are queued messages
            queued_messages = await get_queued_messages(user_id, max_count=1)
            if queued_messages:
                # Log that we found queued messages
                logger.info(f"Found {len(queued_messages)} queued messages for user {user_id}")
                
                # We'll process just one message to avoid prolonged lock holding
                next_message = queued_messages[0]
                
                # Remove it from the queue
                await remove_from_queue(user_id, next_message)
                
                # Update the active command
                await store_active_command(user_id, INSTANCE_ID, next_message)
                
                # Process the next message
                logger.info(f"Processing queued message for user {user_id}: {next_message.get('content', '')[:50]}...")
                await _process_message_internal(next_message)
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
            # Process all matching rules - PASS the complete message_data
            await process_matching_rules(matches, source_type, source_id, chat_id, chat_type, message_data)
        else:
            # No rule matched, but we know which bot received the message
            # Generate a default helpful response
            await handle_no_matches(bot_token, config, source_type, source_id, chat_id, chat_type)
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        service_status.record_error(e)

async def process_matching_rules(matches, source_type, source_id, chat_id, chat_type, original_message_data=None):
    """Process all matching rules and generate responses."""
    for bot, rule in matches:
        response_type = rule.get("response_type", "")
        response_content = rule.get("response_content", "")
        
        # Get the correct token to respond with
        response_token = bot.get("token")
        bot_name = bot.get("bot_name", "unnamed")
        
        logger.info(f"Generating response from bot {bot_name} with token ending ...{response_token[-5:] if response_token else 'none'}")
        
        # Extract message_id for reaction management
        message_id = original_message_data.get("message_id") if original_message_data else None
        
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
            await execute_script_response(
                response_content, source_type, source_id, response_token, 
                chat_id, chat_type, original_message, message_id
            )
        elif response_type == "api-chat":
            # New type: API chat response
            # Use the original message for processing
            original_message = rule.get("original_message", "")
            # IMPORTANT: Pass the complete original message data to have access to message_id
            await execute_api_chat_response(original_message, source_type, source_id, response_token, chat_id, chat_type, original_message_data)
        else:
            logger.error(f"Unknown response type: {response_type}")

async def execute_script_response(script_command, source_type, source_id, response_token, chat_id, chat_type, original_message="", message_id=None):
    """Execute a script and send its output as a response."""
    try:
        # Add the processing reaction to show the script is running
        if message_id:
            await add_processing_reaction(source_type, message_id, response_token, chat_id)
        
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
        
        # Update to completed reaction now that script is done
        if message_id:
            await update_to_completed_reaction(source_type, message_id, response_token, chat_id)
    except subprocess.CalledProcessError as e:
        script_response = f"Error executing script: {e}"
        service_status.record_error(e)
        
        # Add error reaction if script failed
        if message_id:
            await add_error_reaction(source_type, message_id, response_token, chat_id)
    except Exception as e:
        script_response = f"Error: {e}"
        service_status.record_error(e)
        
        # Add error reaction for any other exception
        if message_id:
            await add_error_reaction(source_type, message_id, response_token, chat_id)
    
    # Send the response whether successful or not
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

# Update the function signature to accept the original_message_data parameter
async def execute_api_chat_response(message_content, source_type, source_id, response_token, chat_id, chat_type, original_message_data=None):
    """Send message to API chat service and return the response."""
    try:
        # Extract the message content (everything after "bot:")
        if isinstance(message_content, str) and message_content.lower().startswith("bot:"):
            query = message_content[4:].strip()  # Remove 'bot:' and trim spaces
        elif isinstance(message_content, str):
            query = message_content.strip()
        else:
            query = ""
            
        # Log the query being sent to the API
        logger.info(f"Sending request to API chat: {query[:100]}...")
        
        # Create a user_id for queue tracking
        user_id = f"{source_type}:{source_id}"
        
        # Extract the original message ID using the complete message_data object
        original_message_id = None
        
        # First try to get directly from the original_message_data
        if original_message_data and isinstance(original_message_data, dict):
            original_message_id = original_message_data.get("message_id")
            
            # If not found, try numeric ID
            if not original_message_id and "id" in original_message_data:
                original_message_id = original_message_data.get("id")
                
            logger.debug(f"Found message ID in original_message_data: {original_message_id}")
        
        # If we still don't have it, try to get from the message content (backward compatibility)
        if not original_message_id:
            # Try to get from message_content if it's an object
            for key in ["message_id", "id"]:
                if hasattr(message_content, '__dict__') and key in message_content.__dict__:
                    original_message_id = getattr(message_content, key)
                    break
            
            # If message_content is a dict, try to get from there
            if not original_message_id and isinstance(message_content, dict):
                for key in ["message_id", "id"]:
                    if key in message_content:
                        original_message_id = message_content[key]
                        break
        
        # If we still don't have it, generate a fallback ID
        if not original_message_id:
            logger.warning("Could not extract original message ID for reactions")
            # Use a hash of the message content and user ID as a fallback
            import hashlib
            hash_input = f"{user_id}:{query}:{chat_id}"
            original_message_id = hashlib.md5(hash_input.encode()).hexdigest()
            
        # Log the message ID we're using (for debugging)
        logger.info(f"Using message ID for reactions: {original_message_id}")
            
        # Enqueue the request with the message ID and status callback
        request_id = await enqueue_chat_request(
            user_id=user_id,
            message=query,
            source_type=source_type,
            source_id=source_id,
            response_token=response_token,
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=original_message_id,  # Pass the message ID for reactions
            status_callback=handle_request_status_change  # Pass our status callback
        )
        
        # If enqueuing failed
        if not request_id:
            await send_response(source_type, source_id, 
                "Sorry, I couldn't process your request right now. Please try again later.",
                {
                    "bot_token": response_token,
                    "chat_id": chat_id,
                    "chat_type": chat_type
                }
            )
            return
        
        # Get queue position
        position = await get_queue_position(request_id)
        
        # Send queue position information only if not first in line
        if position > 1:
            await send_response(source_type, source_id, 
                f"Your request has been queued. You are position #{position} in line. I'll notify you when it's your turn.",
                {
                    "bot_token": response_token,
                    "chat_id": chat_id,
                    "chat_type": chat_type
                }
            )
        # For position 1, we add the reaction in the status callback
        
    except Exception as e:
        api_response = f"Error queuing request for API chat service: {e}"
        logger.error(f"API chat queue error: {e}")
        service_status.record_error(e)
        
        # Send error response
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

async def handle_request_status_change(request, status, response=None, error=None):
    """
    Handle status changes for a chat API request.
    This function manages reactions based on the request status.
    """
    source_type = request.source_type
    message_id = request.message_id
    bot_token = request.response_token
    chat_id = request.chat_id
    
    # Create a request tracking key
    request_key = f"{source_type}:{chat_id}:{message_id}"
    
    logger.info(f"Request {request.request_id} status changed to {status}")
    
    try:
        if status == "queued":
            # Add processing reaction for the first request in queue
            position = await get_queue_position(request.request_id)
            
            # Track this request
            _active_requests[request_key] = {
                "status": "queued",
                "request_id": request.request_id,
                "position": position
            }
            
            if position == 1:
                await add_processing_reaction(source_type, message_id, bot_token, chat_id)
                
        elif status == "processing":
            # Ensure processing reaction is added when processing starts
            await add_processing_reaction(source_type, message_id, bot_token, chat_id)
            
            # Update tracking
            if request_key in _active_requests:
                _active_requests[request_key]["status"] = "processing"
            
        elif status == "completed":
            # Update reaction from processing to completed
            await update_to_completed_reaction(source_type, message_id, bot_token, chat_id)
            
            # Remove from tracking
            _active_requests.pop(request_key, None)
            
        elif status == "error":
            # Add error reaction
            await add_error_reaction(source_type, message_id, bot_token, chat_id)
            
            # Remove from tracking
            _active_requests.pop(request_key, None)
    
    except Exception as e:
        logger.error(f"Error handling request status change: {e}")
        service_status.record_error(e)
import re
import logging
from bot_logic.core.config import load_bot_config

logger = logging.getLogger(__name__)

def parse_command_with_bot_target(message_text):
    """
    Parse a command that might include @botname format.
    Returns (command, target_bot_username) tuple.
    If no @botname is present, target_bot_username will be None.
    """
    if not message_text.startswith('/'):
        return message_text, None
    
    # Check if the command includes @botname
    parts = message_text.split('@', 1)
    if len(parts) == 2:
        command = parts[0]
        target_bot = parts[1].strip()
        logger.info(f"Detected command '{command}' targeted at bot '{target_bot}'")
        return command, target_bot
    
    return message_text, None

async def ensure_bot_usernames(config):
    """Ensure all bots in config have usernames from Telegram."""
    # This is a placeholder - ideally, we would query Telegram for bot usernames
    # and store them in the config, but for now we'll use a simplified approach
    
    # If bots have a "username" field already, use that
    for bot in config.get("bots", []):
        if not bot.get("username") and bot.get("token") and bot.get("bot_name"):
            # Use bot_name as a fallback if no username is set
            # In a real implementation, we would query Telegram API with the token
            # to get the actual username
            bot["username"] = bot.get("bot_name")
    
    return config

async def find_all_matching_bot_rules(message_text, config, source_bot_token=None, chat_context=None):
    """Find ALL matching bots and rules for the given message text."""
    # Default to 'both' if no context is provided for backward compatibility
    if chat_context is None:
        chat_context = "both"
    
    logger.info(f"Finding ALL matching rules for message in context: {chat_context}")
    
    # Parse command to check if it's targeting a specific bot
    command_part, target_bot_username = parse_command_with_bot_target(message_text)
    
    # List to store all matching bot and rule pairs
    matches = []
    
    # Get bot usernames mapping from tokens to make matching easier
    bot_usernames = {}  # Map from token to username
    for bot in config.get("bots", []):
        if bot.get("username"):
            bot_usernames[bot.get("token")] = bot.get("username")
    
    for bot in config.get("bots", []):
        if not bot.get("enabled", True):
            continue
        
        bot_name = bot.get("bot_name", "unnamed")
        bot_token = bot.get("token")
        bot_username = bot.get("username")
        
        # If command targets a specific bot, skip others
        if target_bot_username and bot_username and target_bot_username.lower() != bot_username.lower():
            logger.info(f"Skipping bot {bot_name} as command targets '{target_bot_username}' but this bot is '{bot_username}'")
            continue
        
        # Handle bot filtering differently based on context:
        # - In channels, all bots should be able to respond
        # - In DMs, only the bot that received the message should respond
        should_skip_bot = False
        if source_bot_token and chat_context == "dm":
            # In DMs, only the bot that received the message should respond
            if source_bot_token != bot_token:
                logger.info(f"Skipping bot {bot_name} in DM context (not the source bot)")
                should_skip_bot = True
        
        if should_skip_bot:
            continue
            
        logger.info(f"Checking bot {bot_name} for matching rules")
        
        for rule in bot.get("rules", []):
            pattern = rule.get("regex", "")
            rule_context = rule.get("context", "both")
            
            # Skip if rule doesn't apply to the current context
            if rule_context != "both" and rule_context != chat_context:
                logger.info(f"Skipping rule with context {rule_context} for message in {chat_context}")
                continue
            
            # Try to match the command part against the rule, not the full message with @botname
            text_to_match = command_part if target_bot_username else message_text
            logger.info(f"Checking regex: '{pattern}' against: '{text_to_match}'")
            
            try:
                if re.match(pattern, text_to_match):
                    logger.info(f"Found matching rule in bot {bot_name}! Response type: {rule.get('response_type', 'unknown')}")
                    # Create a copy of the rule and add the original message
                    rule_copy = rule.copy()
                    rule_copy["original_message"] = message_text
                    matches.append((bot, rule_copy))
            except Exception as e:
                logger.error(f"Error matching regex '{pattern}': {e}")
    
    logger.info(f"Found {len(matches)} matching bot rules")
    return matches

async def get_available_commands(bot_token, config):
    """Get available commands for a specific bot token."""
    bot_name = "Unknown"
    available_commands = []
    
    for bot_config in config.get("bots", []):
        if bot_config.get("token") == bot_token:
            bot_name = bot_config.get("bot_name", "Unknown")
            # Collect available commands from this bot's rules
            for rule in bot_config.get("rules", []):
                pattern = rule.get("regex", "")
                # Extract command from regex if it looks like a command pattern
                if pattern.startswith("^/"):
                    cmd = pattern.strip("^$")
                    available_commands.append(cmd)
    
    return bot_name, available_commands
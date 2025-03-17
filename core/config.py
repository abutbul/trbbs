import os
import logging
import sys
import json
from typing import Dict, Any

# Configure logging
logging_level = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging_level,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Redis Configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
REDIS_TIMEOUT = 5.0  # Timeout for Redis operations

# Bot Configuration
BOT_CONFIG_PATH = os.environ.get("BOT_CONFIG_PATH", "/app/bot_config.json")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# WhatsApp Configuration 
WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "your_verification_token")
WHATSAPP_TOKEN_REFRESH_URL = os.environ.get("WHATSAPP_TOKEN_REFRESH_URL", "")
WHATSAPP_TOKEN_REFRESH_INTERVAL = int(os.environ.get("WHATSAPP_TOKEN_REFRESH_INTERVAL", 21600))
WHATSAPP_AUTO_REFRESH_TOKEN = os.environ.get("WHATSAPP_AUTO_REFRESH_TOKEN", "false").lower() == "true"

# API Configuration
API_CHAT_URL = os.environ.get("API_CHAT_URL", "http://host.docker.internal:8000/message")
API_TIMEOUT = float(os.environ.get("API_TIMEOUT", "190.0"))
API_RETRIES = int(os.environ.get("API_RETRIES", "2"))
API_RETRY_DELAY = float(os.environ.get("API_RETRY_DELAY", "1.0"))

# Queue Configuration
MAX_CONCURRENT_CHAT_REQUESTS = int(os.environ.get("MAX_CONCURRENT_CHAT_REQUESTS", "1"))
ENABLE_QUEUE_WORKER = os.environ.get("ENABLE_QUEUE_WORKER", "true").lower() == "true"
REPLICA_ID = int(os.environ.get("REPLICA_ID", "0"))

# Settings for Telegram bot
ENABLE_REACTIONS = os.environ.get("ENABLE_REACTIONS", "true").lower() == "true"
UPDATE_POLLING_INTERVAL = float(os.environ.get("UPDATE_POLLING_INTERVAL", "5.0"))
UPDATE_TIMEOUT = float(os.environ.get("UPDATE_TIMEOUT", "1.0"))

# Health Server Configuration
HEALTH_SERVER_HOST = '0.0.0.0'
HEALTH_SERVER_PORT = 8080

# Debug Mode
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# Set debug logging if enabled
if DEBUG_MODE or logging_level.upper() == "DEBUG":
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger('httpx').setLevel(logging.DEBUG)
    logging.getLogger('asyncio').setLevel(logging.DEBUG)

def load_bot_config(config_path: str = None) -> Dict[str, Any]:
    """Load bot configuration from the specified path."""
    if config_path is None:
        config_path = BOT_CONFIG_PATH
        
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            
        # Log configuration details (sanitized)
        bot_count = len(config.get('bots', []))
        enabled_bots = sum(1 for bot in config.get('bots', []) if bot.get('enabled', True))
        
        # Log WhatsApp configuration details if present
        wa_info = ""
        if "whatsapp" in config:
            wa_config = config.get("whatsapp", {})
            has_token = bool(wa_config.get("token"))
            has_phone_id = bool(wa_config.get("phone_number_id"))
            is_enabled = wa_config.get("enabled", False)
            wa_info = f", WhatsApp: enabled={is_enabled}, token_present={has_token}, phone_id_present={has_phone_id}"
            
        logger.info(f"Loaded configuration with {bot_count} bots ({enabled_bots} enabled){wa_info}")
        return config
    except Exception as e:
        logger.error(f"Error loading bot config from {config_path}: {e}")
        return {"bots": []}

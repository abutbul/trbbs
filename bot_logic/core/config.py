#!/usr/bin/env python3
import os
import json
import logging
import sys

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
REDIS_TIMEOUT = 5.0  # Timeout for Redis operations

# Bot configuration
BOT_CONFIG_PATH = os.environ.get("BOT_CONFIG_PATH", "/app/bot_config.json")

# Debug Mode
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# Set debug logging if enabled
if DEBUG_MODE:
    logging.getLogger('bot_logic').setLevel(logging.DEBUG)
    logging.getLogger('asyncio').setLevel(logging.DEBUG)

async def load_bot_config():
    """Load and parse bot configuration from file."""
    try:
        with open(BOT_CONFIG_PATH, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logger.error(f"Error loading bot config: {e}")
        return {"bots": []}
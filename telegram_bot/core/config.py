import os
import logging
import sys

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
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

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Health Server Configuration
HEALTH_SERVER_HOST = '0.0.0.0'
HEALTH_SERVER_PORT = 8080

# Debug Mode
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"

# Set debug logging if enabled
if DEBUG_MODE:
    logging.getLogger('telegram_bot').setLevel(logging.DEBUG)
    logging.getLogger('httpx').setLevel(logging.DEBUG)
    logging.getLogger('asyncio').setLevel(logging.DEBUG)

# Update polling configuration
UPDATE_POLLING_INTERVAL = float(os.environ.get("UPDATE_POLLING_INTERVAL", "5.0"))
UPDATE_TIMEOUT = float(os.environ.get("UPDATE_TIMEOUT", "1.0"))
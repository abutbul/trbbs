import os
import json
import time  # Add missing time module import
import logging
import asyncio
import redis
import uvicorn
import requests
from fastapi import FastAPI, Request, Response, Query
from typing import Dict, Any
from datetime import datetime
import traceback
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Set up logging - increase verbosity
logging_level = os.environ.get("LOG_LEVEL", "DEBUG")  # Default to DEBUG for more info
logging.basicConfig(
    level=logging_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("whatsapp_pubsub")

# Configure root logger to match our format (helps with library error messages)
root_logger = logging.getLogger()
root_logger.setLevel(logging_level)
for handler in root_logger.handlers:
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Load configuration
BOT_CONFIG_PATH = os.environ.get("BOT_CONFIG_PATH", "bot_config.json")

# Redis configuration
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_DB = int(os.environ.get("REDIS_DB", 0))

# Webhook verification token
WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "your_verification_token")

# Token refresh settings
TOKEN_REFRESH_URL = os.environ.get("TOKEN_REFRESH_URL", "")
TOKEN_REFRESH_INTERVAL = int(os.environ.get("TOKEN_REFRESH_INTERVAL", 6 * 60 * 60))  # Default 6 hours
AUTO_REFRESH_TOKEN = os.environ.get("AUTO_REFRESH_TOKEN", "false").lower() == "true"

# Create global instance for lifespan context
whatsapp_pubsub_instance = None

class WhatsAppWrapper:
    """Wrapper around the heyoo WhatsApp client to handle errors consistently"""
    
    def __init__(self, token, phone_number_id):
        from heyoo import WhatsApp
        self.client = WhatsApp(token, phone_number_id=phone_number_id)
        self.token = token
        self.phone_number_id = phone_number_id
        self.error_count = 0
        
        # Override the heyoo logger settings
        logging.getLogger("heyoo").setLevel(logging_level)
        logging.getLogger("root").handlers = []  # Remove default handlers
        for handler in root_logger.handlers:
            logging.getLogger("heyoo").addHandler(handler)
    
    def send_message(self, message, recipient_id):
        """Send a message, handling errors consistently"""
        try:
            logger.info(f"WhatsAppWrapper: Sending message to {recipient_id}")
            result = self.client.send_message(message, recipient_id)
            logger.info(f"WhatsAppWrapper: Message sent successfully: {result}")
            # Reset error count on success
            self.error_count = 0
            return True, None
        except Exception as e:
            self.error_count += 1
            error_response = self._extract_error_response(e)
            logger.error(f"WhatsAppWrapper: Failed to send message: {error_response}")
            return False, error_response
    
    def _extract_error_response(self, error):
        """Extract structured error response from various error formats"""
        error_info = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "status_code": None,
            "fb_error": None,
            "is_token_expired": False
        }
        
        try:
            # Try to extract response info
            if hasattr(error, 'response'):
                if hasattr(error.response, 'status_code'):
                    error_info["status_code"] = error.response.status_code
                    
                if hasattr(error.response, 'json'):
                    try:
                        error_data = error.response.json()
                        if 'error' in error_data:
                            error_info["fb_error"] = error_data['error']
                            
                            # Check for token expiration
                            fb_error = error_data['error']
                            if (fb_error.get('code') == 190 or 
                                fb_error.get('type') == 'OAuthException' or
                                'expire' in fb_error.get('message', '').lower()):
                                error_info["is_token_expired"] = True
                    except:
                        pass
                        
                elif hasattr(error.response, 'text'):
                    try:
                        error_data = json.loads(error.response.text)
                        if 'error' in error_data:
                            error_info["fb_error"] = error_data['error']
                            
                            # Check for token expiration
                            fb_error = error_data['error']
                            if (fb_error.get('code') == 190 or 
                                fb_error.get('type') == 'OAuthException' or
                                'expire' in fb_error.get('message', '').lower()):
                                error_info["is_token_expired"] = True
                    except:
                        pass
        except Exception as parse_error:
            logger.debug(f"Error parsing error response: {parse_error}")
            
        # Also check error message for token expiration keywords
        error_msg = str(error).lower()
        if ('token' in error_msg and ('expire' in error_msg or 'invalid' in error_msg)) or error_info["status_code"] == 401:
            error_info["is_token_expired"] = True
            
        return error_info

class WhatsAppPubSub:
    def __init__(self):
        # Initialize Redis client
        logger.info(f"Initializing Redis connection to {REDIS_HOST}:{REDIS_PORT}")
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=10,
            )
            # Test Redis connection
            self.redis_client.ping()
            logger.info("Redis connection successful")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            logger.error(traceback.format_exc())
            raise
            
        # Load bot configuration
        self.bot_config = self._load_bot_config()
        self.whatsapp_client = None  # Will be initialized in setup_whatsapp
        self.health_check_task = None
        self.token_refresh_task = None
        self.last_token_refresh = datetime.now()
        self.token_expiry_detected = False
        
    def _load_bot_config(self) -> Dict:
        """Load bot configuration from the specified path."""
        try:
            with open(BOT_CONFIG_PATH, "r") as f:
                config = json.load(f)
                logger.info(f"Successfully loaded bot configuration from {BOT_CONFIG_PATH}")
                
                # Log WhatsApp configuration details (sanitized)
                if "whatsapp" in config:
                    wa_config = config.get("whatsapp", {})
                    has_token = bool(wa_config.get("token"))
                    has_phone_id = bool(wa_config.get("phone_number_id"))
                    is_enabled = wa_config.get("enabled", False)
                    num_rules = len(wa_config.get("rules", []))
                    
                    logger.info(f"WhatsApp config: token_present={has_token}, "
                                f"phone_id_present={has_phone_id}, enabled={is_enabled}, "
                                f"rules_count={num_rules}")
                else:
                    logger.warning("No WhatsApp configuration found in bot_config.json")
                
                return config
        except Exception as e:
            logger.error(f"Failed to load bot configuration: {e}")
            logger.error(traceback.format_exc())
            return {}

    async def setup_whatsapp(self):
        """Set up WhatsApp client based on config."""
        try:
            # Get WhatsApp API credentials from config
            whatsapp_token = self.bot_config.get("whatsapp", {}).get("token")
            phone_number_id = self.bot_config.get("whatsapp", {}).get("phone_number_id")
            
            logger.debug(f"WhatsApp token length: {len(whatsapp_token) if whatsapp_token else 0}")
            logger.debug(f"WhatsApp phone number ID: {phone_number_id[:5]}... (partial)" if phone_number_id else "None")
            
            if not whatsapp_token or not phone_number_id:
                logger.error("WhatsApp credentials not found in config")
                return False
                
            # Initialize WhatsApp client with our wrapper
            try:
                self.whatsapp_client = WhatsAppWrapper(whatsapp_token, phone_number_id)
                logger.info("WhatsApp client initialized successfully")
                
                # Start periodic health check
                self.health_check_task = asyncio.create_task(self._periodic_health_check())
                
                # Start token refresh task if enabled
                if AUTO_REFRESH_TOKEN and TOKEN_REFRESH_URL:
                    self.token_refresh_task = asyncio.create_task(self._periodic_token_refresh())
                    logger.info(f"Token auto-refresh enabled, interval: {TOKEN_REFRESH_INTERVAL} seconds")
                else:
                    logger.info("Token auto-refresh disabled")
                
                return True
            except Exception as client_error:
                logger.error(f"Error initializing WhatsApp client: {client_error}")
                logger.error(traceback.format_exc())
                return False
                
        except Exception as e:
            logger.error(f"Failed to set up WhatsApp client: {e}")
            logger.error(traceback.format_exc())
            return False

    async def _periodic_health_check(self):
        """Periodically check and log service health status"""
        while True:
            try:
                # Check Redis connection
                redis_ok = False
                try:
                    self.redis_client.ping()
                    redis_ok = True
                except:
                    redis_ok = False
                
                # Check WhatsApp client
                whatsapp_ok = self.whatsapp_client is not None
                
                logger.debug(f"Health check: Redis={redis_ok}, WhatsApp Client={whatsapp_ok}")
                
                # Check subscription status
                try:
                    subs_count = self.redis_client.pubsub_numsub("bot_responses")[0][1]
                    logger.debug(f"Current subscribers to bot_responses: {subs_count}")
                except Exception as e:
                    logger.warning(f"Could not check subscription status: {e}")
                
            except Exception as e:
                logger.error(f"Error in health check: {e}")
            
            await asyncio.sleep(60)  # Check every minute

    async def _periodic_token_refresh(self):
        """Periodically refresh the WhatsApp API token"""
        while True:
            try:
                # Wait for the refresh interval
                await asyncio.sleep(TOKEN_REFRESH_INTERVAL)
                
                # Refresh the token
                success = await self.refresh_token()
                if success:
                    logger.info("Successfully refreshed WhatsApp API token")
                    self.token_expiry_detected = False
                else:
                    logger.error("Failed to refresh WhatsApp API token")
                
            except Exception as e:
                logger.error(f"Error in token refresh task: {e}")
                await asyncio.sleep(60)  # Wait a bit before retrying on error
    
    async def refresh_token(self):
        """Refresh the WhatsApp API token"""
        if not TOKEN_REFRESH_URL:
            logger.warning("Token refresh URL not configured")
            return False
            
        try:
            logger.info(f"Attempting to refresh WhatsApp token from {TOKEN_REFRESH_URL}")
            
            # Make request to token refresh endpoint
            response = requests.get(TOKEN_REFRESH_URL, timeout=30)
            
            if response.status_code == 200:
                # Parse the response and extract new token
                try:
                    data = response.json()
                    new_token = data.get("token")
                    
                    if not new_token:
                        logger.error("Token refresh response did not contain a token")
                        return False
                    
                    # Update the token in memory
                    if hasattr(self, 'whatsapp_client') and self.whatsapp_client:
                        # Update the token in the wrapper client
                        phone_number_id = self.bot_config.get("whatsapp", {}).get("phone_number_id")
                        self.whatsapp_client = WhatsAppWrapper(new_token, phone_number_id)
                        
                        # Update the token in the config
                        if "whatsapp" in self.bot_config:
                            self.bot_config["whatsapp"]["token"] = new_token
                        
                        self.last_token_refresh = datetime.now()
                        logger.info("WhatsApp token refreshed successfully")
                        return True
                    else:
                        logger.error("WhatsApp client not initialized, cannot update token")
                        return False
                        
                except Exception as e:
                    logger.error(f"Error processing token refresh response: {e}")
                    return False
            else:
                logger.error(f"Token refresh failed with status {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error refreshing WhatsApp token: {e}")
            logger.error(traceback.format_exc())
            return False

    async def publish_message(self, message: Dict[str, Any]):
        """Publish a message to Redis for processing by bot-logic."""
        try:
            # Add source to identify the platform
            message["source"] = "whatsapp"
            message["timestamp"] = datetime.utcnow().isoformat()
            
            # Serialize and publish to the same queue used by Telegram
            message_json = json.dumps(message)
            result = self.redis_client.lpush("message_queue", message_json)
            logger.info(f"Published message to Redis: {message} (result: {result})")
            return True
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            logger.error(traceback.format_exc())
            return False

    async def handle_webhook(self, data: Dict[str, Any]):
        """Process incoming webhook data from WhatsApp."""
        try:
            logger.info(f"Processing webhook data: {json.dumps(data)}")
            
            # Check if this is a status update (not a message)
            if "statuses" in str(data):
                logger.info("Received status update, not a message")
                return True
                
            # Extract message content based on WhatsApp Cloud API structure
            entries = data.get("entry", [])
            if not entries:
                logger.warning("No entries in webhook data")
                return False
                
            messages_processed = 0
            
            for entry in entries:
                changes = entry.get("changes", [])
                if not changes:
                    logger.debug(f"No changes in entry: {entry}")
                    continue
                    
                for change in changes:
                    value = change.get("value", {})
                    messages = value.get("messages", [])
                    
                    if not messages:
                        logger.debug(f"No messages in value: {value}")
                        continue
                    
                    for msg in messages:
                        msg_type = msg.get("type")
                        logger.debug(f"Processing message of type: {msg_type}")
                        
                        if msg_type == "text":
                            # Extract relevant information
                            message = {
                                "message_id": msg.get("id"),
                                "chat_id": msg.get("from"),
                                "text": msg.get("text", {}).get("body", ""),
                                "user_id": msg.get("from"),
                                "username": "",  # WhatsApp doesn't provide username
                                "timestamp": datetime.utcnow().isoformat()
                            }
                            
                            logger.info(f"Extracted message: {message}")
                            
                            # Publish to Redis for bot-logic to process
                            success = await self.publish_message(message)
                            if success:
                                messages_processed += 1
                            
                        else:
                            logger.info(f"Ignoring non-text message of type: {msg_type}")
            
            logger.info(f"Processed {messages_processed} messages from webhook data")
            return True
        except Exception as e:
            logger.error(f"Error handling webhook data: {e}")
            logger.error(traceback.format_exc())
            return False

    async def send_whatsapp_message(self, chat_id, text):
        """Send a message to WhatsApp with error handling for token expiration"""
        if not self.whatsapp_client:
            logger.error("WhatsApp client not initialized")
            return False
            
        try:
            logger.info(f"Sending message to WhatsApp user {chat_id}: {text[:50]}...")
            
            # Use our wrapper instead of directly accessing the client
            success, error_info = self.whatsapp_client.send_message(text, chat_id)
            
            if success:
                logger.info(f"Successfully sent message to WhatsApp user {chat_id}")
                return True
            
            # Handle token expiration if detected
            if error_info and error_info.get("is_token_expired", False):
                self.token_expiry_detected = True
                logger.error(f"WhatsApp token has expired: {error_info}")
                
                # Try to refresh the token immediately
                if TOKEN_REFRESH_URL:
                    logger.info("Attempting immediate token refresh...")
                    refresh_success = await self.refresh_token()
                    
                    if refresh_success:
                        # Retry sending the message with refreshed token
                        logger.info("Retrying message send after token refresh")
                        retry_success, retry_error = self.whatsapp_client.send_message(text, chat_id)
                        
                        if retry_success:
                            logger.info(f"Successfully sent message after token refresh to {chat_id}")
                            return True
                        
                        logger.error(f"Failed to send message after token refresh: {retry_error}")
                        return False
                    
                    logger.error("Token refresh failed")
                    return False
                
                logger.warning("Token refresh URL not configured, cannot refresh expired token")
                return False
            
            # Other error occurred
            logger.error(f"Error sending WhatsApp message: {error_info}")
            return False
                
        except Exception as e:
            logger.error(f"Unexpected error in send_whatsapp_message: {e}")
            logger.error(traceback.format_exc())
            return False

    async def subscribe_to_responses(self):
        """Subscribe to bot responses from Redis and send to WhatsApp."""
        try:
            logger.info("Setting up subscription to bot_responses channel")
            pubsub = self.redis_client.pubsub()
            pubsub.subscribe("bot_responses")
            
            logger.info("Subscribed to bot_responses channel")
            
            while True:
                try:
                    message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message["type"] == "message":
                        try:
                            # Parse the response message
                            response = json.loads(message["data"])
                            logger.debug(f"Received bot response: {response}")
                            
                            # Only handle responses meant for WhatsApp
                            if response.get("source") == "whatsapp":
                                chat_id = response.get("chat_id")
                                text = response.get("text", "")
                                
                                if chat_id and text:
                                    # Send the message to WhatsApp
                                    await self.send_whatsapp_message(chat_id, text)
                                else:
                                    if not chat_id:
                                        logger.warning("Missing chat_id in response")
                                    if not text:
                                        logger.warning("Missing text in response")
                        except json.JSONDecodeError:
                            logger.error(f"Invalid JSON in bot response: {message['data']}")
                        except Exception as e:
                            logger.error(f"Error processing bot response: {e}")
                            logger.error(traceback.format_exc())
                    
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error in message processing loop: {e}")
                    logger.error(traceback.format_exc())
                    await asyncio.sleep(1)  # Shorter delay on errors
                    
        except Exception as e:
            logger.error(f"Error in response subscription: {e}")
            logger.error(traceback.format_exc())
            # Attempt to reconnect after a delay
            await asyncio.sleep(5)
            logger.info("Attempting to reconnect to Redis subscription")
            asyncio.create_task(self.subscribe_to_responses())


# Set up FastAPI with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize on startup
    global whatsapp_pubsub_instance
    whatsapp_pubsub_instance = WhatsAppPubSub()
    
    # Initialize WhatsApp client
    await whatsapp_pubsub_instance.setup_whatsapp()
    
    # Start subscription to bot responses
    response_task = asyncio.create_task(whatsapp_pubsub_instance.subscribe_to_responses())
    
    logger.info("WhatsApp PubSub service started")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down WhatsApp PubSub service")
    if whatsapp_pubsub_instance.health_check_task:
        whatsapp_pubsub_instance.health_check_task.cancel()
    
    if whatsapp_pubsub_instance.token_refresh_task:
        whatsapp_pubsub_instance.token_refresh_task.cancel()
    
    # Cancel subscription task if running
    if response_task and not response_task.done():
        response_task.cancel()
        try:
            await response_task
        except asyncio.CancelledError:
            pass

app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create health check endpoint
@app.get("/health")
async def health_check():
    # Check Redis connection
    redis_status = "healthy"
    try:
        if whatsapp_pubsub_instance and whatsapp_pubsub_instance.redis_client:
            whatsapp_pubsub_instance.redis_client.ping()
        else:
            redis_status = "not initialized"
    except Exception as e:
        redis_status = f"error: {str(e)}"
    
    # Check WhatsApp client
    whatsapp_status = "ready" if whatsapp_pubsub_instance and whatsapp_pubsub_instance.whatsapp_client else "not initialized"
    
    return {
        "status": "healthy" if redis_status == "healthy" and whatsapp_status == "ready" else "degraded",
        "service": "whatsapp-pubsub",
        "redis": redis_status,
        "whatsapp_client": whatsapp_status,
        "timestamp": datetime.utcnow().isoformat()
    }

# Debug endpoint to check environment and configuration
@app.get("/debug")
async def debug_info():
    """Return debug information about the service (sanitized)"""
    config_info = {}
    token_info = {}
    if whatsapp_pubsub_instance:
        wa_config = whatsapp_pubsub_instance.bot_config.get("whatsapp", {})
        config_info = {
            "has_token": bool(wa_config.get("token")),
            "has_phone_id": bool(wa_config.get("phone_number_id")),
            "enabled": wa_config.get("enabled", False),
            "rules_count": len(wa_config.get("rules", [])),
        }
        
        token_info = {
            "auto_refresh_enabled": AUTO_REFRESH_TOKEN,
            "refresh_interval_hours": TOKEN_REFRESH_INTERVAL / 3600,
            "refresh_url_configured": bool(TOKEN_REFRESH_URL),
            "last_refresh": whatsapp_pubsub_instance.last_token_refresh.isoformat() 
                            if hasattr(whatsapp_pubsub_instance, 'last_token_refresh') else None,
            "expiry_detected": whatsapp_pubsub_instance.token_expiry_detected
        }
    
    return {
        "service": "whatsapp-pubsub",
        "redis_configured": bool(whatsapp_pubsub_instance and whatsapp_pubsub_instance.redis_client),
        "whatsapp_configured": bool(whatsapp_pubsub_instance and whatsapp_pubsub_instance.whatsapp_client),
        "config_info": config_info,
        "token_info": token_info,
        "bot_config_path": BOT_CONFIG_PATH,
        "redis_host": REDIS_HOST,
        "redis_port": REDIS_PORT,
        "webhook_token_configured": bool(WEBHOOK_VERIFY_TOKEN and WEBHOOK_VERIFY_TOKEN != "your_verification_token")
    }

# Add verification endpoint for WhatsApp
@app.get("/webhook")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")
):
    logger.info(f"Webhook verification request received: mode={mode}, token_present={bool(token)}, challenge_present={bool(challenge)}")
    logger.debug(f"Comparing tokens: received={token}, expected={WEBHOOK_VERIFY_TOKEN}")
    
    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        logger.info(f"Webhook verified successfully with challenge: {challenge}")
        return Response(content=challenge)
    else:
        logger.warning(f"Webhook verification failed: mode={mode}, token_match={token == WEBHOOK_VERIFY_TOKEN}")
        return Response(content="Verification failed", status_code=403)

# Improved webhook endpoint
@app.post("/webhook")
async def webhook(request: Request):
    logger.info("Received POST to /webhook endpoint")
    
    # Log headers for debugging
    headers = dict(request.headers.items())
    sanitized_headers = {k: v for k, v in headers.items() if "token" not in k.lower()}
    logger.info(f"Request headers: {sanitized_headers}")  # Changed to INFO level for better visibility
    
    # Get raw body for debugging
    body_bytes = await request.body()
    try:
        body_text = body_bytes.decode('utf-8')
        logger.info(f"Raw request body: {body_text}")  # Changed to INFO level
        
        # Parse JSON body
        data = json.loads(body_text)
        logger.info(f"Parsed webhook data with keys: {list(data.keys())}")
        
        if whatsapp_pubsub_instance:
            await whatsapp_pubsub_instance.handle_webhook(data)
        else:
            logger.error("WhatsApp PubSub instance not initialized")
            
        return Response(content="EVENT_RECEIVED")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        logger.error(traceback.format_exc())
        return Response(content="Error processing request", status_code=500)

# Add in-container test endpoints
@app.post("/test-webhook")
async def test_webhook(request: Request):
    """Test endpoint to simulate webhook events for troubleshooting"""
    logger.info("Received POST to /test-webhook endpoint")
    
    try:
        # Get raw body
        body_bytes = await request.body()
        body_text = body_bytes.decode('utf-8')
        logger.info(f"Test webhook raw body: {body_text}")
        
        # Parse JSON body
        data = json.loads(body_text)
        
        # Simulate a WhatsApp message structure if not provided
        if "entry" not in data:
            # Create a simulated WhatsApp message structure
            test_message = data.get("message", "Test message")
            test_from = data.get("from", "123456789")
            
            simulated_data = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "id": f"test_msg_{int(time.time())}",
                                            "from": test_from,
                                            "type": "text",
                                            "text": {
                                                "body": test_message
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            
            logger.info(f"Simulated webhook data: {json.dumps(simulated_data)}")
            data = simulated_data
        
        if whatsapp_pubsub_instance:
            result = await whatsapp_pubsub_instance.handle_webhook(data)
            return {
                "status": "processed" if result else "failed", 
                "message": "Test webhook processed successfully" if result else "Failed to process test webhook",
                "data": data
            }
        else:
            return {"status": "error", "message": "WhatsApp PubSub instance not initialized"}
            
    except Exception as e:
        logger.error(f"Error processing test webhook: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

# Create simple HTML form for testing inside container
@app.get("/test-ui")
async def test_ui():
    """Simple HTML interface for testing WhatsApp webhook inside container"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Webhook Tester</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }
            h1 { color: #0066cc; }
            .container { max-width: 800px; margin: 0 auto; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, textarea { width: 100%; padding: 8px; box-sizing: border-box; }
            button { padding: 10px 15px; background: #0066cc; color: white; border: none; cursor: pointer; }
            .response { margin-top: 20px; padding: 15px; background: #f5f5f5; border-left: 5px solid #0066cc; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>WhatsApp Webhook Test Tool</h1>
            <p>Use this form to test your WhatsApp webhook without external tools. This simulates a message from WhatsApp.</p>
            
            <div class="form-group">
                <label for="from">From (Phone Number):</label>
                <input type="text" id="from" name="from" value="123456789">
            </div>
            
            <div class="form-group">
                <label for="message">Message Text:</label>
                <textarea id="message" name="message" rows="4">Test message</textarea>
            </div>
            
            <button onclick="testWebhook()">Send Test Message</button>
            
            <div id="response" class="response" style="display: none;"></div>
            
            <script>
                async function testWebhook() {
                    const from = document.getElementById('from').value;
                    const message = document.getElementById('message').value;
                    const responseDiv = document.getElementById('response');
                    
                    responseDiv.textContent = 'Sending request...';
                    responseDiv.style.display = 'block';
                    
                    try {
                        const response = await fetch('/test-webhook', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                from: from,
                                message: message
                            })
                        });
                        
                        const data = await response.json();
                        responseDiv.textContent = JSON.stringify(data, null, 2);
                    } catch (error) {
                        responseDiv.textContent = 'Error: ' + error.message;
                    }
                }
            </script>
        </div>
    </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")

# Simple test endpoint
@app.get("/test-send")
async def test_send(message: str = "Test message", to: str = None):
    """Test endpoint to send a message to a WhatsApp user"""
    if not to:
        return {"error": "Missing 'to' parameter"}
        
    if whatsapp_pubsub_instance:
        # Use the enhanced send method that handles token expiration
        success = await whatsapp_pubsub_instance.send_whatsapp_message(to, message)
        if success:
            return {"status": "sent", "to": to, "message": message}
        else:
            return {"status": "error", "message": "Failed to send message, see logs for details"}
    else:
        return {"error": "WhatsApp client not initialized"}

# Add token refresh endpoint
@app.post("/refresh-token")
async def manual_token_refresh():
    """Manually trigger a token refresh"""
    if not whatsapp_pubsub_instance:
        return {
            "status": "error", 
            "message": "WhatsApp service not initialized",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    # Get current token info before refresh
    current_token_info = {
        "expiry_detected": whatsapp_pubsub_instance.token_expiry_detected,
        "last_refresh": whatsapp_pubsub_instance.last_token_refresh.isoformat(),
    }
        
    success = await whatsapp_pubsub_instance.refresh_token()
    
    if success:
        return {
            "status": "success", 
            "message": "Token refreshed successfully",
            "previous_state": current_token_info,
            "current_state": {
                "expiry_detected": whatsapp_pubsub_instance.token_expiry_detected,
                "last_refresh": whatsapp_pubsub_instance.last_token_refresh.isoformat(),
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    else:
        return {
            "status": "error", 
            "message": "Failed to refresh token",
            "current_state": current_token_info,
            "timestamp": datetime.utcnow().isoformat()
        }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)

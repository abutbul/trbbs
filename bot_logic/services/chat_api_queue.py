import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple, Callable
import uuid
import hashlib

from bot_logic.services.redis_service import get_redis
from bot_logic.services.api_service import send_chat_message
from bot_logic.services.response_service import send_response
from bot_logic.core.status import service_status
from bot_logic.services.reaction_service import update_to_completed_reaction
from bot_logic.services.redis_queue_manager import RedisQueueManager, STATUS_QUEUED, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_ERROR

logger = logging.getLogger(__name__)

# Redis keys (kept for backward compatibility)
CHAT_API_LOCK_KEY = "chat_api:lock"
CHAT_API_QUEUE_KEY = "chat_api:queue"
CHAT_API_STATUS_KEY = "chat_api:status"
CHAT_API_STATS_KEY = "chat_api:stats"

# Lock duration in seconds
LOCK_EXPIRY = 300  # 5 minutes max for a single request
QUEUE_ITEM_EXPIRY = 3600  # 1 hour max for queue items

# Background worker control
_worker_task = None
_should_stop = False

# Initialize the Redis Queue Manager
_queue_manager = RedisQueueManager(
    prefix="chat_api",
    default_ttl=QUEUE_ITEM_EXPIRY
)

# Configure the queue manager
_queue_manager.lock_expiry = LOCK_EXPIRY
_queue_manager.max_retries = 3
_queue_manager.retry_delay_base = 5  # 5 seconds base delay

# In-memory storage for callbacks
_callbacks = {}

class QueuedRequest:
    """
    Represents a queued chat API request.
    Maintained for backward compatibility.
    """
    def __init__(self, request_id: str, user_id: str, message: str, 
                source_type: str, source_id: str, response_token: str,
                chat_id: str, chat_type: str, message_id: str = None,
                status_callback: Callable = None):
        self.request_id = request_id
        self.user_id = user_id
        self.message = message
        self.source_type = source_type
        self.source_id = source_id
        self.response_token = response_token
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.message_id = message_id  # Store original message ID for reactions
        self.timestamp = time.time()
        self.status_callback = status_callback  # Callback for status updates
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "message": self.message,
            "source_type": self.source_type,
            "source_id": self.source_id, 
            "response_token": self.response_token,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "message_id": self.message_id,
            "timestamp": self.timestamp
            # status_callback is not serializable, so we don't include it
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueuedRequest':
        return cls(
            request_id=data.get("request_id", ""),
            user_id=data.get("user_id", ""),
            message=data.get("message", ""),
            source_type=data.get("source_type", ""),
            source_id=data.get("source_id", ""),
            response_token=data.get("response_token", ""),
            chat_id=data.get("chat_id", ""),
            chat_type=data.get("chat_type", ""),
            message_id=data.get("message_id", ""),
        )

    async def notify_status(self, status, response=None, error=None):
        """Notify status callback if available"""
        if self.status_callback:
            try:
                await self.status_callback(self, status, response, error)
            except Exception as e:
                logger.error(f"Error in status callback: {e}")


async def enqueue_chat_request(user_id: str, message: str, 
                              source_type: str, source_id: str, 
                              response_token: str, chat_id: str, 
                              chat_type: str, message_id: str, 
                              status_callback: Callable = None) -> str:
    """
    Add a chat request to the queue and return the request ID.
    If the user already has a request in the queue, update it.
    
    The status_callback, if provided, will be called with 
    (request, status, response, error) when the request status changes.
    """
    try:
        # Create a unique request ID
        request_id = str(uuid.uuid4())
        
        # Create message data
        message_data = {
            "request_id": request_id,
            "user_id": user_id,
            "message": message,
            "source_type": source_type,
            "source_id": source_id,
            "response_token": response_token,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_id": message_id,
            "timestamp": time.time(),
            "status": STATUS_QUEUED
        }
        
        # Store callback for status updates
        if status_callback:
            # Create a wrapper callback that converts to QueuedRequest
            async def callback_wrapper(message_data, status, response=None, error=None):
                request = QueuedRequest.from_dict(message_data)
                await status_callback(request, status, response, error)
            
            # Store the callback wrapper
            _callbacks[request_id] = callback_wrapper
        
        # Enqueue the request
        result_id = await _queue_manager.enqueue(message_data, 
                                               callback=_callbacks.get(request_id))
        
        if result_id:
            # If we got back a different ID, it means a duplicate was found
            if result_id != request_id:
                logger.info(f"Duplicate request detected, using existing ID: {result_id}")
                # Update the callback for the existing request
                if status_callback:
                    _callbacks[result_id] = _callbacks.pop(request_id)
            
            return result_id
        else:
            logger.error("Failed to enqueue chat request")
            return None
            
    except Exception as e:
        logger.error(f"Error enqueueing chat request: {e}")
        service_status.record_error(e)
        return None
        
async def get_queue_position(request_id: str) -> int:
    """Get the current position of a request in the queue."""
    try:
        return await _queue_manager.get_position(request_id)
    except Exception as e:
        logger.error(f"Error getting queue position: {e}")
        return -1

async def get_user_request(user_id: str) -> Optional[QueuedRequest]:
    """Get the current request for a user if they have one in the queue."""
    redis = await get_redis()
    if not redis:
        return None
        
    try:
        # Get all messages in the main queue
        message_ids = await redis.zrange(_queue_manager.queue_main_key, 0, -1)
        
        # Check each message
        for message_id in message_ids:
            message_id = message_id.decode('utf-8') if isinstance(message_id, bytes) else message_id
            message_data = await _queue_manager.get_message(message_id)
            
            if message_data and message_data.get("user_id") == user_id:
                return QueuedRequest.from_dict(message_data)
                
        return None
    except Exception as e:
        logger.error(f"Error getting user request: {e}")
        return None

async def get_queue_length() -> int:
    """Get the current length of the chat API queue."""
    try:
        return await _queue_manager.get_queue_length(include_retry=True)
    except Exception as e:
        logger.error(f"Error getting queue length: {e}")
        return 0

async def try_acquire_chat_api_lock(timeout: int = 0) -> bool:
    """
    Try to acquire the chat API lock.
    
    Args:
        timeout: If >0, wait up to this many seconds for the lock
    
    Returns:
        True if lock was acquired, False otherwise
    """
    try:
        return await _queue_manager.try_acquire_lock(
            "global_lock",  # Use a fixed ID for the global lock
            "processor",    # Owner identifier
            timeout=timeout
        )
    except Exception as e:
        logger.error(f"Error acquiring chat API lock: {e}")
        return False

async def release_chat_api_lock() -> bool:
    """Release the chat API lock."""
    try:
        return await _queue_manager.release_lock(
            "global_lock",  # Use a fixed ID for the global lock
            "processor"     # Owner identifier
        )
    except Exception as e:
        logger.error(f"Error releasing chat API lock: {e}")
        return False

async def process_chat_api_queue():
    """Background worker to process the chat API queue."""
    global _should_stop
    
    logger.info("Chat API queue processor started")
    
    while not _should_stop:
        try:
            # Try to acquire the lock
            lock_acquired = await try_acquire_chat_api_lock()
            
            if not lock_acquired:
                # No lock, wait and try again
                logger.debug("Chat API is busy, waiting to retry")
                await asyncio.sleep(1)
                continue
                
            # Get next request from queue
            next_message_id = await _queue_manager.get_next_message()
            
            if not next_message_id:
                # No requests in queue, release lock and wait
                await release_chat_api_lock()
                await asyncio.sleep(1)
                continue
                
            # Get the message data
            message_data = await _queue_manager.get_message(next_message_id)
            if not message_data:
                # Message disappeared, release lock and continue
                await release_chat_api_lock()
                continue
                
            # Convert to QueuedRequest for backward compatibility
            next_request = QueuedRequest.from_dict(message_data)
            
            # Process the request
            logger.info(f"Processing chat API request for user {next_request.user_id}")
            
            # Update status to "processing"
            await _queue_manager.update_message(next_message_id, {"status": STATUS_PROCESSING})
            
            # Notify that request is processing
            callback = _callbacks.get(next_message_id)
            if callback:
                await callback(message_data, STATUS_PROCESSING)
            
            # Actually process the request
            await process_chat_request(next_request)
            
            # Remove the request from queue
            await _queue_manager.remove_message(next_message_id)
            
            # Release the lock for the next worker
            await release_chat_api_lock()
            
        except Exception as e:
            logger.error(f"Error in chat API queue processor: {e}")
            service_status.record_error(e)
            
            # Make sure we release the lock if we encountered an error
            await release_chat_api_lock()
            
            # Wait a bit before retrying
            await asyncio.sleep(2)
    
    logger.info("Chat API queue processor stopped")

async def get_next_request() -> Optional[QueuedRequest]:
    """Get the next request from the queue."""
    try:
        # Get next message ID
        message_id = await _queue_manager.get_next_message()
        if not message_id:
            return None
            
        # Get message data
        message_data = await _queue_manager.get_message(message_id)
        if not message_data:
            return None
            
        # Convert to QueuedRequest
        return QueuedRequest.from_dict(message_data)
    except Exception as e:
        logger.error(f"Error getting next request: {e}")
        return None

async def update_request_status(request_id: str, status: str) -> bool:
    """Update the status of a request in Redis."""
    try:
        return await _queue_manager.update_message(request_id, {"status": status})
    except Exception as e:
        logger.error(f"Error updating request status: {e}")
        return False

async def remove_request(request_id: str) -> bool:
    """Remove a request from the queue."""
    try:
        result = await _queue_manager.remove_message(request_id)
        # Clean up callback
        _callbacks.pop(request_id, None)
        return result
    except Exception as e:
        logger.error(f"Error removing request: {e}")
        return False

async def process_chat_request(request: QueuedRequest):
    """Process a chat API request."""
    try:
        # Make the actual API call
        logger.info(f"Sending request to chat API: {request.message[:100]}...")
        success, response, error = await send_chat_message(request.message)
        
        # Send the response back to the user
        if success and response:
            api_response = response
            # Notify about successful completion
            await request.notify_status(STATUS_COMPLETED, response)
            await update_to_completed_reaction(request.source_type, request.message_id, request.response_token, request.chat_id)
        else:
            api_response = f"Error communicating with chat API: {error}"
            logger.error(f"Chat API error: {error}")
            
            # Notify about error
            await request.notify_status(STATUS_ERROR, None, error)
            
        # Send the response
        await send_response(
            request.source_type,
            request.source_id,
            api_response,
            {
                "bot_token": request.response_token,
                "chat_id": request.chat_id,
                "chat_type": request.chat_type
            }
        )
        
        # Update stats
        redis = await get_redis()
        if redis:
            await redis.hincrby(CHAT_API_STATS_KEY, "processed_requests", 1)
            
    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        service_status.record_error(e)
        
        # Notify about error
        await request.notify_status(STATUS_ERROR, None, str(e))
        
        # Send error response
        try:
            await send_response(
                request.source_type,
                request.source_id,
                f"Sorry, there was an error processing your request: {str(e)}",
                {
                    "bot_token": request.response_token,
                    "chat_id": request.chat_id,
                    "chat_type": request.chat_type
                }
            )
        except Exception as e2:
            logger.error(f"Error sending error response: {e2}")

async def start_queue_processor():
    """Start the background queue processor."""
    global _worker_task, _should_stop
    
    if _worker_task is not None:
        logger.warning("Queue processor already running")
        return
        
    _should_stop = False
    _worker_task = asyncio.create_task(process_chat_api_queue())
    logger.info("Started chat API queue processor")

async def stop_queue_processor():
    """Stop the background queue processor."""
    global _worker_task, _should_stop
    
    if _worker_task is None:
        logger.warning("Queue processor not running")
        return
        
    _should_stop = True
    try:
        await asyncio.wait_for(_worker_task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("Queue processor did not stop gracefully, cancelling")
        _worker_task.cancel()
        
    _worker_task = None
    logger.info("Stopped chat API queue processor")

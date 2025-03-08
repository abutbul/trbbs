import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple, Callable
import uuid

from bot_logic.services.redis_service import get_redis
from bot_logic.services.api_service import send_chat_message
from bot_logic.services.response_service import send_response
from bot_logic.core.status import service_status
from bot_logic.services.reaction_service import update_to_completed_reaction

logger = logging.getLogger(__name__)

# Redis keys
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

# Status constants
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"

class QueuedRequest:
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
    redis = await get_redis()
    if not redis:
        logger.error("Failed to get Redis connection for enqueueing chat request")
        return None
        
    # Create a unique request ID
    request_id = str(uuid.uuid4())
    
    # Create the request object with message_id and status callback
    request = QueuedRequest(
        request_id=request_id,
        user_id=user_id,
        message=message,
        source_type=source_type,
        source_id=source_id,
        response_token=response_token,
        chat_id=chat_id,
        chat_type=chat_type,
        message_id=message_id,
        status_callback=status_callback
    )
    
    # First check if user already has a request in the queue
    # If so, we'll update it instead of adding a new one
    existing_requests = await redis.hgetall(CHAT_API_QUEUE_KEY)
    
    # Track if we're updating an existing request
    updating_existing = False
    
    for req_id, req_data in existing_requests.items():
        try:
            req = json.loads(req_data)
            if req.get("user_id") == user_id:
                # Check if this is a different message or the same message as before
                if req.get("message_id") != message_id:
                    # User already has a request, update it
                    logger.info(f"Updating existing chat request for user {user_id}")
                    request.request_id = req_id  # Keep the same request ID
                    await redis.hset(CHAT_API_QUEUE_KEY, req_id, json.dumps(request.to_dict()))
                    updating_existing = True
                    # Notify about the update via callback
                    await request.notify_status(STATUS_QUEUED)
                    return req_id
                else:
                    # This is a duplicate request for the same message, ignore it
                    logger.info(f"Ignoring duplicate chat request for same message_id: {message_id}")
                    return req_id
        except Exception as e:
            logger.error(f"Error parsing existing request: {e}")
    
    # Add new request to queue
    try:
        await redis.hset(CHAT_API_QUEUE_KEY, request_id, json.dumps(request.to_dict()))
        await redis.expire(CHAT_API_QUEUE_KEY, QUEUE_ITEM_EXPIRY)  # Set expiry on the queue
        
        # Get current queue position for this request
        position = await get_queue_position(request_id)
        logger.info(f"Added request {request_id} to chat API queue at position {position}")
        
        # Update stats
        await redis.hincrby(CHAT_API_STATS_KEY, "total_requests", 1)
        
        # Notify that request is queued
        await request.notify_status(STATUS_QUEUED)
        
        return request_id
    except Exception as e:
        logger.error(f"Error enqueueing chat request: {e}")
        return None
        
async def get_queue_position(request_id: str) -> int:
    """Get the current position of a request in the queue."""
    redis = await get_redis()
    if not redis:
        return -1
        
    try:
        # Get all requests in the queue
        requests = await redis.hgetall(CHAT_API_QUEUE_KEY)
        
        # Sort by timestamp
        sorted_requests = []
        for req_id, req_data in requests.items():
            try:
                req = json.loads(req_data)
                sorted_requests.append((req_id, req.get("timestamp", 0)))
            except Exception:
                continue
                
        sorted_requests.sort(key=lambda x: x[1])  # Sort by timestamp
        
        # Find position of our request
        for i, (req_id, _) in enumerate(sorted_requests):
            if req_id == request_id:
                return i + 1  # 1-based position
                
        return -1  # Not found
    except Exception as e:
        logger.error(f"Error getting queue position: {e}")
        return -1

async def get_user_request(user_id: str) -> Optional[QueuedRequest]:
    """Get the current request for a user if they have one in the queue."""
    redis = await get_redis()
    if not redis:
        return None
        
    try:
        requests = await redis.hgetall(CHAT_API_QUEUE_KEY)
        
        for req_data in requests.values():
            try:
                req = json.loads(req_data)
                if req.get("user_id") == user_id:
                    return QueuedRequest.from_dict(req)
            except Exception:
                continue
                
        return None
    except Exception as e:
        logger.error(f"Error getting user request: {e}")
        return None

async def get_queue_length() -> int:
    """Get the current length of the chat API queue."""
    redis = await get_redis()
    if not redis:
        return 0
        
    try:
        return await redis.hlen(CHAT_API_QUEUE_KEY)
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
    redis = await get_redis()
    if not redis:
        return False
        
    if timeout <= 0:
        # Just try once
        try:
            locked = await redis.set(
                CHAT_API_LOCK_KEY, 
                "1", 
                nx=True,  # Only set if not exists
                ex=LOCK_EXPIRY  # Auto-expire to prevent deadlocks
            )
            return locked
        except Exception as e:
            logger.error(f"Error acquiring chat API lock: {e}")
            return False
    else:
        # Try for specified timeout
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                locked = await redis.set(
                    CHAT_API_LOCK_KEY, 
                    "1", 
                    nx=True,
                    ex=LOCK_EXPIRY
                )
                if locked:
                    return True
            except Exception as e:
                logger.error(f"Error acquiring chat API lock: {e}")
                
            # Wait a bit before retrying
            await asyncio.sleep(0.5)
            
        return False

async def release_chat_api_lock() -> bool:
    """Release the chat API lock."""
    redis = await get_redis()
    if not redis:
        return False
        
    try:
        await redis.delete(CHAT_API_LOCK_KEY)
        return True
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
            next_request = await get_next_request()
            
            if not next_request:
                # No requests in queue, release lock and wait
                await release_chat_api_lock()
                await asyncio.sleep(1)
                continue
                
            # Process the request
            logger.info(f"Processing chat API request for user {next_request.user_id}")
            
            # Update status to "processing"
            await update_request_status(next_request.request_id, STATUS_PROCESSING)
            
            # Notify that request is processing
            await next_request.notify_status(STATUS_PROCESSING)
            
            # Actually process the request
            await process_chat_request(next_request)
            
            # Remove the request from queue
            await remove_request(next_request.request_id)
            
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
    redis = await get_redis()
    if not redis:
        return None
        
    try:
        # Get all requests and sort by timestamp
        requests = await redis.hgetall(CHAT_API_QUEUE_KEY)
        
        if not requests:
            return None
            
        # Parse and sort by timestamp
        parsed_requests = []
        for req_id, req_data in requests.items():
            try:
                req_dict = json.loads(req_data)
                parsed_requests.append((req_id, req_dict.get("timestamp", 0), req_dict))
            except Exception as e:
                logger.error(f"Error parsing request data: {e}")
                continue
                
        if not parsed_requests:
            return None
            
        # Sort by timestamp (oldest first)
        parsed_requests.sort(key=lambda x: x[1])
        
        # Get the oldest request
        _, _, req_dict = parsed_requests[0]
        
        # Convert to QueuedRequest object
        return QueuedRequest.from_dict(req_dict)
    except Exception as e:
        logger.error(f"Error getting next request: {e}")
        return None

async def update_request_status(request_id: str, status: str) -> bool:
    """Update the status of a request in Redis."""
    redis = await get_redis()
    if not redis:
        return False
        
    try:
        # Get the request
        req_data = await redis.hget(CHAT_API_QUEUE_KEY, request_id)
        if not req_data:
            return False
            
        # Parse and update status
        req_dict = json.loads(req_data)
        req_dict["status"] = status
        
        # Save back to Redis
        await redis.hset(CHAT_API_QUEUE_KEY, request_id, json.dumps(req_dict))
        return True
    except Exception as e:
        logger.error(f"Error updating request status: {e}")
        return False

async def remove_request(request_id: str) -> bool:
    """Remove a request from the queue."""
    redis = await get_redis()
    if not redis:
        return False
        
    try:
        await redis.hdel(CHAT_API_QUEUE_KEY, request_id)
        return True
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

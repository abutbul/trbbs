import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, List, Tuple, Callable, Union

import redis.asyncio as aioredis
from bot_logic.core.status import service_status
from bot_logic.services.redis_service import get_redis

logger = logging.getLogger(__name__)

# Status constants
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_ERROR = "error"
STATUS_RETRY = "retry"

class RedisQueueManager:
    """
    Redis-based message queue manager with improved reliability and persistence.
    
    Features:
    - Message persistence with TTL
    - Deduplication
    - Retry mechanism with exponential backoff
    - Dead letter queue for failed messages
    - Atomic operations using Redis transactions
    - Queue monitoring and statistics
    """
    
    def __init__(self, prefix: str, default_ttl: int = 3600):
        """
        Initialize the queue manager.
        
        Args:
            prefix: Prefix for all Redis keys used by this queue
            default_ttl: Default TTL for queue items in seconds (default: 1 hour)
        """
        self.prefix = prefix
        self.default_ttl = default_ttl
        
        # Redis key templates
        self.queue_main_key = f"{prefix}:queue:main"
        self.queue_retry_key = f"{prefix}:queue:retry"
        self.queue_dlq_key = f"{prefix}:queue:dlq"
        self.msg_prefix = f"{prefix}:msg:"
        self.dedup_prefix = f"{prefix}:dedup:"
        self.lock_prefix = f"{prefix}:lock:"
        self.stats_key = f"{prefix}:stats"
        
        # Default settings
        self.max_retries = 3
        self.retry_delay_base = 5  # Base delay in seconds
        self.lock_expiry = 300  # 5 minutes
        self.dedup_expiry = 3600  # 1 hour
        
        # Background worker control
        self._worker_task = None
        self._should_stop = False
    
    async def enqueue(self, message_data: Dict[str, Any], 
                     callback: Optional[Callable] = None) -> Tuple[Optional[str], bool]:
        """
        Add a message to the queue with deduplication.
        
        Args:
            message_data: Message data to enqueue
            callback: Optional callback function for status updates
            
        Returns:
            Tuple of (Message ID, is_duplicate) if successful, (None, False) otherwise
        """
        redis = await get_redis()
        if not redis:
            logger.error("Failed to get Redis connection for enqueueing message")
            return None, False
        
        try:
            # Generate a unique message ID if not provided
            message_id = message_data.get("request_id", str(uuid.uuid4()))
            
            # Add message ID to the data
            message_data["request_id"] = message_id
            
            # Add timestamp if not present
            if "timestamp" not in message_data:
                message_data["timestamp"] = time.time()
            
            # Add status if not present
            if "status" not in message_data:
                message_data["status"] = STATUS_QUEUED
                
            # Add retry count if not present
            if "retry_count" not in message_data:
                message_data["retry_count"] = 0
            
            # Check for duplicate message based on content hash
            if "message" in message_data and "user_id" in message_data:
                dedup_key = self._get_dedup_key(message_data["user_id"], message_data["message"])
                existing_id = await redis.get(dedup_key)
                
                if existing_id:
                    existing_id = existing_id.decode('utf-8') if isinstance(existing_id, bytes) else existing_id
                    
                    # Get the existing message to check its status and age
                    should_deduplicate = True
                    existing_msg = await self.get_message(existing_id)
                    
                    if existing_msg:
                        # Don't deduplicate if the message has already been processed
                        if existing_msg.get("status") in [STATUS_COMPLETED, STATUS_ERROR]:
                            logger.info(f"Message with ID {existing_id} already processed, allowing new request")
                            should_deduplicate = False
                            # Clear the dedup key since the message is already processed
                            await self.clear_deduplication_key(message_data["user_id"], message_data["message"])
                        else:
                            # Check if the message is older than 2 minutes
                            now = time.time()
                            msg_time = float(existing_msg.get("timestamp", 0))
                            if now - msg_time > 120:  # 2 minutes in seconds
                                logger.info(f"Message with ID {existing_id} is older than 2 minutes, allowing new request")
                                should_deduplicate = False
                                # Clear old deduplication key
                                await self.clear_deduplication_key(message_data["user_id"], message_data["message"])
                    
                    if should_deduplicate:
                        logger.info(f"Duplicate message detected, returning existing ID: {existing_id}")
                        # Store the dedup key in the message data for later reference
                        if existing_msg:
                            await self.update_message(existing_id, {"dedup_key": dedup_key})
                        return existing_id, True  # Return tuple with is_duplicate=True
                
                # Store deduplication key with expiry
                await redis.set(dedup_key, message_id, ex=self.dedup_expiry)
                # Store the dedup key in the message data for later reference
                message_data["dedup_key"] = dedup_key
            
            # Store the message data as a hash
            msg_key = self._get_message_key(message_id)
            
            # Store callback separately since it's not serializable
            message_data_copy = message_data.copy()
            message_data_copy["_has_callback"] = callback is not None
            
            # Use pipeline for atomic operations
            async with redis.pipeline(transaction=True) as pipe:
                # Store message data
                await pipe.hset(msg_key, mapping=self._serialize_dict(message_data_copy))
                await pipe.expire(msg_key, self.default_ttl)
                
                # Add to main queue with score as timestamp for FIFO ordering
                await pipe.zadd(self.queue_main_key, {message_id: message_data["timestamp"]})
                
                # Update stats
                await pipe.hincrby(self.stats_key, "total_messages", 1)
                
                # Execute all commands
                await pipe.execute()
            
            # Store callback in memory (can't be serialized to Redis)
            if callback:
                self._store_callback(message_id, callback)
            
            # Get current queue position
            position = await self.get_position(message_id)
            logger.info(f"Added message {message_id} to queue at position {position}")
            
            # Notify about queued status
            await self._notify_status(message_id, STATUS_QUEUED)
            
            return message_id, False  # Return tuple with is_duplicate=False
            
        except Exception as e:
            logger.error(f"Error enqueueing message: {e}")
            service_status.record_error(e)
            return None, False
    
    async def get_position(self, message_id: str) -> int:
        """
        Get the current position of a message in the queue.
        
        Args:
            message_id: The message ID
            
        Returns:
            Position in queue (1-based) or -1 if not found
        """
        redis = await get_redis()
        if not redis:
            return -1
        
        try:
            # Get rank in the sorted set (0-based)
            rank = await redis.zrank(self.queue_main_key, message_id)
            
            if rank is not None:
                return rank + 1  # Convert to 1-based position
            
            # Check retry queue if not in main queue
            rank = await redis.zrank(self.queue_retry_key, message_id)
            if rank is not None:
                # Add main queue length to get overall position
                main_len = await redis.zcard(self.queue_main_key)
                return main_len + rank + 1
                
            return -1  # Not found in any queue
            
        except Exception as e:
            logger.error(f"Error getting message position: {e}")
            return -1
    
    async def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a message by ID.
        
        Args:
            message_id: The message ID
            
        Returns:
            Message data or None if not found
        """
        redis = await get_redis()
        if not redis:
            return None
        
        try:
            msg_key = self._get_message_key(message_id)
            data = await redis.hgetall(msg_key)
            
            if not data:
                return None
                
            return self._deserialize_dict(data)
            
        except Exception as e:
            logger.error(f"Error getting message: {e}")
            return None
    
    async def update_message(self, message_id: str, 
                           updates: Dict[str, Any]) -> bool:
        """
        Update a message's data.
        
        Args:
            message_id: The message ID
            updates: Dictionary of fields to update
            
        Returns:
            True if successful, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        try:
            msg_key = self._get_message_key(message_id)
            
            # Check if message exists
            exists = await redis.exists(msg_key)
            if not exists:
                logger.warning(f"Attempted to update non-existent message: {message_id}")
                return False
            
            # Update only the specified fields
            serialized_updates = self._serialize_dict(updates)
            await redis.hset(msg_key, mapping=serialized_updates)
            
            # Reset expiry
            await redis.expire(msg_key, self.default_ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating message: {e}")
            return False
    
    async def remove_message(self, message_id: str) -> bool:
        """
        Remove a message from all queues and storage.
        
        Args:
            message_id: The message ID
            
        Returns:
            True if successful, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        try:
            # First, clear any deduplication key associated with this message
            await self.clear_deduplication_key_by_id(message_id)
            
            msg_key = self._get_message_key(message_id)
            
            # Use pipeline for atomic operations
            async with redis.pipeline(transaction=True) as pipe:
                # Remove from all queues
                await pipe.zrem(self.queue_main_key, message_id)
                await pipe.zrem(self.queue_retry_key, message_id)
                await pipe.zrem(self.queue_dlq_key, message_id)
                
                # Remove message data
                await pipe.delete(msg_key)
                
                # Execute all commands
                await pipe.execute()
            
            # Remove callback if exists
            self._remove_callback(message_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error removing message: {e}")
            return False
    
    async def move_to_dlq(self, message_id: str, error: str) -> bool:
        """
        Move a message to the dead letter queue after max retries.
        
        Args:
            message_id: The message ID
            error: Error message to store
            
        Returns:
            True if successful, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        try:
            # Get message data
            message = await self.get_message(message_id)
            if not message:
                return False
            
            # Update message with error info
            message["status"] = STATUS_ERROR
            message["error"] = error
            message["moved_to_dlq_at"] = time.time()
            
            # Use pipeline for atomic operations
            async with redis.pipeline(transaction=True) as pipe:
                # Update message data
                msg_key = self._get_message_key(message_id)
                await pipe.hset(msg_key, mapping=self._serialize_dict(message))
                
                # Remove from main and retry queues
                await pipe.zrem(self.queue_main_key, message_id)
                await pipe.zrem(self.queue_retry_key, message_id)
                
                # Add to DLQ with current timestamp
                await pipe.zadd(self.queue_dlq_key, {message_id: time.time()})
                
                # Update stats
                await pipe.hincrby(self.stats_key, "dlq_messages", 1)
                
                # Execute all commands
                await pipe.execute()
            
            # Notify about error status
            await self._notify_status(message_id, STATUS_ERROR, error=error)
            
            return True
            
        except Exception as e:
            logger.error(f"Error moving message to DLQ: {e}")
            return False
    
    async def retry_message(self, message_id: str) -> bool:
        """
        Move a message to the retry queue with exponential backoff.
        
        Args:
            message_id: The message ID
            
        Returns:
            True if successful, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        try:
            # Get message data
            message = await self.get_message(message_id)
            if not message:
                return False
            
            # Check retry count
            retry_count = message.get("retry_count", 0)
            
            if retry_count >= self.max_retries:
                # Move to DLQ if max retries reached
                error = message.get("last_error", "Max retries exceeded")
                return await self.move_to_dlq(message_id, error)
            
            # Calculate next retry time with exponential backoff
            retry_count += 1
            backoff = self.retry_delay_base * (2 ** (retry_count - 1))  # Exponential backoff
            next_retry = time.time() + backoff
            
            # Update message
            message["retry_count"] = retry_count
            message["next_retry"] = next_retry
            message["status"] = STATUS_RETRY
            
            # Use pipeline for atomic operations
            async with redis.pipeline(transaction=True) as pipe:
                # Update message data
                msg_key = self._get_message_key(message_id)
                await pipe.hset(msg_key, mapping=self._serialize_dict(message))
                
                # Remove from main queue
                await pipe.zrem(self.queue_main_key, message_id)
                
                # Add to retry queue with score as next retry time
                await pipe.zadd(self.queue_retry_key, {message_id: next_retry})
                
                # Update stats
                await pipe.hincrby(self.stats_key, "retry_count", 1)
                
                # Execute all commands
                await pipe.execute()
            
            # Notify about retry status
            await self._notify_status(message_id, STATUS_RETRY)
            
            logger.info(f"Scheduled message {message_id} for retry in {backoff:.1f}s (attempt {retry_count}/{self.max_retries})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error retrying message: {e}")
            return False
    
    async def get_next_message(self) -> Optional[str]:
        """
        Get the next message ID to process from main queue or retry queue.
        
        Returns:
            Message ID or None if no messages are ready
        """
        redis = await get_redis()
        if not redis:
            return None
        
        try:
            # First check main queue
            main_result = await redis.zrange(self.queue_main_key, 0, 0)
            if main_result:
                return main_result[0].decode('utf-8') if isinstance(main_result[0], bytes) else main_result[0]
            
            # Then check retry queue for messages ready to retry
            now = time.time()
            retry_result = await redis.zrangebyscore(self.queue_retry_key, 0, now, start=0, num=1)
            
            if retry_result:
                message_id = retry_result[0].decode('utf-8') if isinstance(retry_result[0], bytes) else retry_result[0]
                
                # Move from retry queue back to main queue
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.zrem(self.queue_retry_key, message_id)
                    await pipe.zadd(self.queue_main_key, {message_id: now})
                    await pipe.execute()
                
                return message_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting next message: {e}")
            return None
    
    async def get_queue_length(self, include_retry: bool = True, include_dlq: bool = False) -> int:
        """
        Get the current length of the queue.
        
        Args:
            include_retry: Whether to include retry queue in count
            include_dlq: Whether to include dead letter queue in count
            
        Returns:
            Queue length
        """
        redis = await get_redis()
        if not redis:
            return 0
        
        try:
            # Get main queue length
            main_len = await redis.zcard(self.queue_main_key)
            total = main_len
            
            # Add retry queue if requested
            if include_retry:
                retry_len = await redis.zcard(self.queue_retry_key)
                total += retry_len
            
            # Add DLQ if requested
            if include_dlq:
                dlq_len = await redis.zcard(self.queue_dlq_key)
                total += dlq_len
            
            return total
            
        except Exception as e:
            logger.error(f"Error getting queue length: {e}")
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dictionary of statistics
        """
        redis = await get_redis()
        if not redis:
            return {}
        
        try:
            # Get stored stats
            stats = await redis.hgetall(self.stats_key)
            stats = self._deserialize_dict(stats)
            
            # Add current queue lengths
            stats["main_queue_length"] = await redis.zcard(self.queue_main_key)
            stats["retry_queue_length"] = await redis.zcard(self.queue_retry_key)
            stats["dlq_length"] = await redis.zcard(self.queue_dlq_key)
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting queue stats: {e}")
            return {}
    
    async def try_acquire_lock(self, message_id: str, owner: str, timeout: int = 0) -> bool:
        """
        Try to acquire a processing lock for a message.
        
        Args:
            message_id: The message ID
            owner: Identifier for the lock owner
            timeout: If >0, wait up to this many seconds for the lock
            
        Returns:
            True if lock was acquired, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        lock_key = self._get_lock_key(message_id)
        
        if timeout <= 0:
            # Just try once
            try:
                locked = await redis.set(
                    lock_key, 
                    owner, 
                    nx=True,  # Only set if not exists
                    ex=self.lock_expiry  # Auto-expire to prevent deadlocks
                )
                return locked
            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")
                return False
        else:
            # Try for specified timeout
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    locked = await redis.set(
                        lock_key, 
                        owner, 
                        nx=True,
                        ex=self.lock_expiry
                    )
                    if locked:
                        return True
                except Exception as e:
                    logger.error(f"Error acquiring lock: {e}")
                    
                # Wait a bit before retrying
                await asyncio.sleep(0.5)
                
            return False
    
    async def release_lock(self, message_id: str, owner: str) -> bool:
        """
        Release a processing lock for a message, but only if we own it.
        
        Args:
            message_id: The message ID
            owner: Identifier for the lock owner
            
        Returns:
            True if lock was released, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
        
        lock_key = self._get_lock_key(message_id)
        
        try:
            # Check if we own the lock
            lock_holder = await redis.get(lock_key)
            lock_holder = lock_holder.decode('utf-8') if isinstance(lock_holder, bytes) else lock_holder
            
            if lock_holder == owner:
                # We own the lock, delete it
                await redis.delete(lock_key)
                return True
            elif lock_holder:
                # Someone else owns the lock
                logger.warning(f"Cannot release lock for message {message_id} - owned by {lock_holder}, not {owner}")
                return False
            else:
                # Lock doesn't exist anymore
                return True
                
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")
            return False
    
    async def start_processor(self, process_func: Callable, poll_interval: float = 1.0):
        """
        Start the background queue processor.
        
        Args:
            process_func: Function to process messages, should accept message_id
            poll_interval: How often to check for new messages in seconds
        """
        if self._worker_task is not None:
            logger.warning("Queue processor already running")
            return
        
        self._should_stop = False
        self._worker_task = asyncio.create_task(
            self._process_queue(process_func, poll_interval)
        )
        logger.info(f"Started queue processor for {self.prefix}")
    
    async def stop_processor(self, timeout: float = 5.0):
        """
        Stop the background queue processor.
        
        Args:
            timeout: How long to wait for graceful shutdown in seconds
        """
        if self._worker_task is None:
            logger.warning("Queue processor not running")
            return
        
        self._should_stop = True
        try:
            await asyncio.wait_for(self._worker_task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Queue processor did not stop gracefully, cancelling")
            self._worker_task.cancel()
            
        self._worker_task = None
        logger.info(f"Stopped queue processor for {self.prefix}")
    
    async def _process_queue(self, process_func: Callable, poll_interval: float):
        """
        Background worker to process the queue.
        
        Args:
            process_func: Function to process messages
            poll_interval: How often to check for new messages in seconds
        """
        logger.info(f"Queue processor started for {self.prefix}")
        
        while not self._should_stop:
            try:
                # Get next message to process
                message_id = await self.get_next_message()
                
                if not message_id:
                    # No messages in queue, wait and try again
                    await asyncio.sleep(poll_interval)
                    continue
                
                # Process the message
                logger.info(f"Processing message {message_id}")
                
                # Update status to processing
                await self.update_message(message_id, {"status": STATUS_PROCESSING})
                
                # Notify that message is processing
                await self._notify_status(message_id, STATUS_PROCESSING)
                
                # Call the process function
                try:
                    await process_func(message_id)
                except Exception as e:
                    logger.error(f"Error processing message {message_id}: {e}")
                    service_status.record_error(e)
                    
                    # Update message with error
                    await self.update_message(message_id, {
                        "last_error": str(e),
                        "last_error_time": time.time()
                    })
                    
                    # Move to retry queue
                    await self.retry_message(message_id)
                
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")
                service_status.record_error(e)
                
                # Wait a bit before retrying
                await asyncio.sleep(poll_interval)
        
        logger.info(f"Queue processor stopped for {self.prefix}")
    
    async def _notify_status(self, message_id: str, status: str, response: Any = None, error: str = None):
        """
        Notify status callback for a message if available.
        
        Args:
            message_id: The message ID
            status: New status
            response: Optional response data
            error: Optional error message
        """
        try:
            # Get message data
            message = await self.get_message(message_id)
            if not message:
                return
            
            # Check if message has a callback
            if not message.get("_has_callback", False):
                return
            
            # Get callback from memory
            callback = self._get_callback(message_id)
            if not callback:
                return
            
            # Call the callback
            await callback(message, status, response, error)
            
        except Exception as e:
            logger.error(f"Error in status callback for message {message_id}: {e}")
    
    # Helper methods
    def _get_message_key(self, message_id: str) -> str:
        """Get Redis key for message data."""
        return f"{self.msg_prefix}{message_id}"
    
    def _get_lock_key(self, message_id: str) -> str:
        """Get Redis key for message lock."""
        return f"{self.lock_prefix}{message_id}"
    
    def _get_dedup_key(self, user_id: str, message: str) -> str:
        """Get Redis key for message deduplication."""
        # Create a hash of the message content for deduplication
        message_hash = hashlib.md5(f"{user_id}:{message}".encode()).hexdigest()
        return f"{self.dedup_prefix}{message_hash}"
    
    def _serialize_dict(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Convert dictionary values to strings for Redis storage."""
        result = {}
        for key, value in data.items():
            if isinstance(value, (dict, list, tuple, set)):
                result[key] = json.dumps(value)
            else:
                result[key] = str(value)
        return result
    
    def _deserialize_dict(self, data: Dict[str, str]) -> Dict[str, Any]:
        """Convert dictionary values from strings to appropriate types."""
        result = {}
        for key, value in data.items():
            # Decode bytes to string if needed
            if isinstance(value, bytes):
                value = value.decode('utf-8')
                
            # Try to parse JSON for complex types
            if key not in ("_has_callback", "retry_count", "timestamp", "next_retry"):
                try:
                    result[key] = json.loads(value)
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # Convert numeric strings to numbers
            if key in ("retry_count", "timestamp", "next_retry"):
                try:
                    if "." in value:
                        result[key] = float(value)
                    else:
                        result[key] = int(value)
                    continue
                except (ValueError, TypeError):
                    pass
            
            # Convert boolean strings
            if value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
                continue
                
            # Keep as string for other values
            result[key] = value
            
        return result
    
    # Callback storage (in-memory)
    _callbacks = {}
    
    def _store_callback(self, message_id: str, callback: Callable):
        """Store callback function in memory."""
        self._callbacks[message_id] = callback
    
    def _get_callback(self, message_id: str) -> Optional[Callable]:
        """Get callback function from memory."""
        return self._callbacks.get(message_id)
    
    def _remove_callback(self, message_id: str):
        """Remove callback function from memory."""
        self._callbacks.pop(message_id, None)
    
    async def clear_deduplication_key(self, user_id: str, message: str) -> bool:
        """
        Clear a deduplication key for a user's message.
        
        Args:
            user_id: User identifier
            message: Message content
            
        Returns:
            True if the key was cleared, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
            
        try:
            # Generate the deduplication key
            dedup_key = self._get_dedup_key(user_id, message)
            
            # Delete the key
            await redis.delete(dedup_key)
            logger.info(f"Cleared deduplication key for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error clearing deduplication key: {e}")
            return False
            
    async def clear_deduplication_key_by_id(self, message_id: str) -> bool:
        """
        Clear a deduplication key for a message by its ID.
        
        Args:
            message_id: Message identifier
            
        Returns:
            True if the key was cleared, False otherwise
        """
        redis = await get_redis()
        if not redis:
            return False
            
        try:
            # Get the message
            message = await self.get_message(message_id)
            if not message:
                logger.warning(f"Message {message_id} not found when trying to clear dedup key")
                return False
                
            # Check if the message has a stored dedup_key
            dedup_key = message.get("dedup_key")
            if dedup_key:
                # Delete the key directly
                await redis.delete(dedup_key)
                logger.info(f"Cleared stored deduplication key for message {message_id}")
                return True
                
            # If no stored key, try to regenerate it
            user_id = message.get("user_id")
            msg_content = message.get("message")
            if user_id and msg_content:
                return await self.clear_deduplication_key(user_id, msg_content)
                
            logger.warning(f"Could not determine deduplication key for message {message_id}")
            return False
        except Exception as e:
            logger.error(f"Error clearing deduplication key by ID: {e}")
            return False
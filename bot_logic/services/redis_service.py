import json
import logging
import asyncio
import redis.asyncio as aioredis
from bot_logic.core.config import REDIS_URL, REDIS_TIMEOUT
from bot_logic.core.status import service_status

logger = logging.getLogger(__name__)

# Global Redis connection pool
redis_pool = None

# Redis lock keys constants
USER_LOCK_PREFIX = "user_lock:"
USER_LOCK_EXPIRY = 90  # seconds - should match or exceed API_TIMEOUT
MESSAGE_CLAIM_PREFIX = "msg_claim:"
MESSAGE_CLAIM_EXPIRY = 300  # 5 minutes

async def get_redis_pool():
    """Get or create the Redis connection pool."""
    global redis_pool
    
    if redis_pool is None:
        logger.info(f"Creating Redis connection pool to {REDIS_URL.replace('redis://:', 'redis://***:')}")
        redis_pool = aioredis.ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=10
        )
    
    return redis_pool

async def get_redis():
    """Get a Redis client from the connection pool."""
    pool = await get_redis_pool()
    return aioredis.Redis(connection_pool=pool)

async def initialize_redis():
    """Initialize the Redis connection."""
    try:
        redis = await get_redis()
        await asyncio.wait_for(redis.ping(), timeout=REDIS_TIMEOUT)
        logger.info("Initialized Redis connection")
        service_status.set_redis_status(True)
        return redis
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        service_status.set_redis_status(False)
        service_status.record_error(e)
        return None

async def cleanup_redis():
    """Close the Redis connection pool."""
    global redis_pool
    if redis_pool:
        await redis_pool.disconnect()
        redis_pool = None
        logger.info("Closed Redis connection pool")

async def publish_message(channel, message_data):
    """Publish a message to Redis."""
    try:
        redis = await get_redis()
        
        # Convert to JSON if needed
        if isinstance(message_data, dict):
            message_data = json.dumps(message_data)
        
        # Publish with timeout
        result = await asyncio.wait_for(
            redis.publish(channel, message_data),
            timeout=REDIS_TIMEOUT
        )
        
        # Update connection status
        service_status.set_redis_status(True)
        return result > 0
    
    except Exception as e:
        logger.error(f"Error publishing to Redis: {e}")
        service_status.set_redis_status(False)
        service_status.record_error(e)
        return False

async def subscribe_to_channel(channel):
    """Subscribe to a Redis channel."""
    try:
        redis = await get_redis()
        pubsub = redis.pubsub()
        
        # Subscribe with timeout
        await asyncio.wait_for(
            pubsub.subscribe(channel),
            timeout=REDIS_TIMEOUT
        )
        
        logger.info(f"Successfully subscribed to channel: {channel}")
        service_status.set_redis_status(True)
        return pubsub
    except Exception as e:
        logger.error(f"Failed to subscribe to Redis channel {channel}: {e}")
        service_status.set_redis_status(False)
        service_status.record_error(e)
        return None

async def get_message(pubsub, timeout=1.0):
    """Get a message from a PubSub channel with timeout."""
    try:
        message = await asyncio.wait_for(
            pubsub.get_message(ignore_subscribe_messages=True),
            timeout=timeout
        )
        return message
    except asyncio.TimeoutError:
        # This is expected when no message is available
        return None
    except Exception as e:
        logger.error(f"Error getting message from Redis: {e}")
        service_status.set_redis_status(False)
        service_status.record_error(e)
        return None

async def close_pubsub(pubsub):
    """Close a PubSub connection safely."""
    if pubsub:
        try:
            await pubsub.unsubscribe()
            await pubsub.close()
        except Exception as e:
            logger.error(f"Error closing Redis pubsub: {e}")

async def try_claim_message(message_id, instance_id):
    """
    Try to claim a message for processing by this instance.
    Returns True if the message was claimed successfully, False otherwise.
    """
    if not message_id:
        return False
        
    redis_client = await get_redis()
    if not redis_client:
        return False
    
    claim_key = f"{MESSAGE_CLAIM_PREFIX}{message_id}"
    
    try:
        # Try to set the key only if it doesn't exist (NX option)
        result = await redis_client.set(
            claim_key, 
            instance_id,
            nx=True,  # Only set if key doesn't exist
            ex=MESSAGE_CLAIM_EXPIRY  # Auto-expire to prevent deadlocks
        )
        
        if result:
            logger.info(f"Claimed message {message_id} by instance {instance_id}")
            return True
        else:
            # Check who holds the claim
            claim_holder = await redis_client.get(claim_key)
            logger.info(f"Message {message_id} already claimed by instance {claim_holder}")
            return False
            
    except Exception as e:
        logger.error(f"Error claiming message {message_id}: {e}")
        return False

async def try_lock_user(user_id, instance_id):
    """
    Try to acquire a lock for a user to prevent multiple instances
    from processing messages from the same user simultaneously.
    
    Returns True if lock was acquired, False otherwise.
    """
    if not user_id:
        return False
        
    redis_client = await get_redis()
    if not redis_client:
        return False
    
    lock_key = f"{USER_LOCK_PREFIX}{user_id}"
    
    try:
        # Try to set the key only if it doesn't exist
        result = await redis_client.set(
            lock_key, 
            instance_id,
            nx=True,  # Only set if key doesn't exist
            ex=USER_LOCK_EXPIRY  # Auto-expire to prevent deadlocks
        )
        
        if result:
            logger.info(f"Acquired lock for user {user_id} by instance {instance_id}")
            return True
        else:
            # Check who holds the lock
            lock_holder = await redis_client.get(lock_key)
            logger.info(f"User {user_id} is locked by instance {lock_holder}")
            return False
            
    except Exception as e:
        logger.error(f"Error acquiring lock for user {user_id}: {e}")
        return False

async def release_user_lock(user_id, instance_id):
    """
    Release a user lock, but only if we own it.
    """
    if not user_id:
        return False
        
    redis_client = await get_redis()
    if not redis_client:
        return False
    
    lock_key = f"{USER_LOCK_PREFIX}{user_id}"
    
    try:
        # Check if we own the lock
        lock_holder = await redis_client.get(lock_key)
        
        if lock_holder == instance_id:
            # We own the lock, delete it
            await redis_client.delete(lock_key)
            logger.info(f"Released lock for user {user_id} by instance {instance_id}")
            return True
        elif lock_holder:
            # Someone else owns the lock
            logger.warning(f"Cannot release lock for user {user_id} - owned by {lock_holder}, not {instance_id}")
            return False
        else:
            # Lock doesn't exist anymore
            logger.info(f"Lock for user {user_id} already released")
            return True
            
    except Exception as e:
        logger.error(f"Error releasing lock for user {user_id}: {e}")
        return False
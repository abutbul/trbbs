import json
import logging
import asyncio
import redis.asyncio as aioredis
from bot_logic.core.config import REDIS_URL, REDIS_TIMEOUT
from bot_logic.core.status import service_status

logger = logging.getLogger(__name__)

# Global Redis connection pool
redis_pool = None

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
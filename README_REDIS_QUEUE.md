# Redis Queue Implementation

This document describes the new Redis-based message queue implementation for the chat API service.

## Overview

The new implementation provides a robust, reliable message queue system with the following features:

- **Message Persistence**: All messages are stored in Redis with configurable TTL
- **Deduplication**: Prevents duplicate messages from being processed
- **Retry Mechanism**: Failed messages are automatically retried with exponential backoff
- **Dead Letter Queue**: Messages that fail after max retries are moved to a DLQ for inspection
- **Atomic Operations**: Uses Redis transactions to ensure data consistency
- **Distributed Locking**: Prevents race conditions in distributed environments
- **Queue Monitoring**: Provides statistics and monitoring capabilities

## Architecture

The implementation consists of two main components:

1. **RedisQueueManager**: A generic Redis-based queue manager that can be used for any type of message queue
2. **ChatApiQueue**: A specific implementation for the chat API service that maintains backward compatibility

### Redis Key Structure

```
chat_api:
  ├── queue:main              # Sorted set for main message queue (score = timestamp)
  ├── queue:retry             # Sorted set for retry queue
  ├── queue:dlq               # Dead letter queue for failed messages
  ├── msg:{message_id}        # Hash containing message details
  ├── dedup:{message_hash}    # Deduplication keys
  ├── lock:{message_id}       # Processing locks
  └── stats                   # Hash for basic statistics
```

## Usage

### Basic Usage

```python
from bot_logic.services.chat_api_queue import (
    enqueue_chat_request, get_queue_position, get_user_request,
    get_queue_length, process_chat_request, start_queue_processor,
    stop_queue_processor
)

# Enqueue a request
request_id = await enqueue_chat_request(
    user_id="user123",
    message="Hello, world!",
    source_type="telegram",
    source_id="chat123",
    response_token="bot_token",
    chat_id="chat123",
    chat_type="private",
    message_id="msg123",
    status_callback=my_callback_function
)

# Get queue position
position = await get_queue_position(request_id)

# Get queue length
length = await get_queue_length()

# Start the queue processor
await start_queue_processor()

# Stop the queue processor
await stop_queue_processor()
```

### Advanced Usage with RedisQueueManager

```python
from bot_logic.services.redis_queue_manager import RedisQueueManager

# Create a custom queue manager
queue_manager = RedisQueueManager(
    prefix="my_queue",
    default_ttl=3600  # 1 hour
)

# Configure the queue manager
queue_manager.max_retries = 5
queue_manager.retry_delay_base = 10  # 10 seconds base delay
queue_manager.lock_expiry = 300  # 5 minutes

# Enqueue a message
message_id = await queue_manager.enqueue({
    "user_id": "user123",
    "message": "Hello, world!",
    "timestamp": time.time()
})

# Define a processing function
async def process_message(message_id):
    # Get the message
    message = await queue_manager.get_message(message_id)
    
    # Process the message
    # ...
    
    # Update status
    await queue_manager.update_message(message_id, {"status": "completed"})
    
    # Remove from queue
    await queue_manager.remove_message(message_id)

# Start the queue processor
await queue_manager.start_processor(process_message, poll_interval=1.0)

# Stop the queue processor
await queue_manager.stop_processor()
```


## Deployment

### Prerequisites

- Redis server (version 5.0 or higher recommended)
- Python 3.7 or higher
- redis-py library (version 4.0 or higher)

### Configuration

The Redis connection is configured through environment variables:

- `REDIS_HOST`: Redis server hostname (default: "redis")
- `REDIS_PORT`: Redis server port (default: 6379)
- `REDIS_PASSWORD`: Redis server password (default: "")
- `REDIS_DB`: Redis database number (default: 0)
- `REDIS_TIMEOUT`: Redis operation timeout in seconds (default: 5.0)



## Monitoring and Maintenance

### Queue Statistics

The queue manager provides statistics through the `get_stats()` method:

```python
stats = await queue_manager.get_stats()
print(f"Main queue length: {stats['main_queue_length']}")
print(f"Retry queue length: {stats['retry_queue_length']}")
print(f"DLQ length: {stats['dlq_length']}")
print(f"Total messages: {stats['total_messages']}")
```

### Dead Letter Queue Management

Messages in the dead letter queue can be inspected and reprocessed:

```python
# Get all messages in the DLQ
dlq_messages = await redis.zrange(queue_manager.queue_dlq_key, 0, -1)

# Reprocess a message from DLQ
message_id = dlq_messages[0]
await queue_manager.update_message(message_id, {
    "retry_count": 0,
    "status": "queued"
})
await redis.zrem(queue_manager.queue_dlq_key, message_id)
await redis.zadd(queue_manager.queue_main_key, {message_id: time.time()})
```

## Troubleshooting

### Common Issues

1. **Redis Connection Failures**:
   - Check Redis server is running
   - Verify connection settings (host, port, password)
   - Check network connectivity

2. **Messages Stuck in Processing**:
   - Check for crashed worker processes
   - Verify lock expiry settings
   - Manually release locks if needed

3. **High Memory Usage**:
   - Reduce TTL for queue items
   - Implement periodic cleanup of old messages
   - Monitor Redis memory usage

### Debugging

Enable debug logging to see detailed queue operations:

```python
import logging
logging.getLogger('bot_logic').setLevel(logging.DEBUG)
```

## Future Improvements

1. **Queue Prioritization**: Implement priority queues for important messages
2. **Rate Limiting**: Add rate limiting to prevent queue flooding
3. **Web Dashboard**: Create a web interface for queue monitoring and management
4. **Batch Processing**: Implement batch processing for higher throughput
5. **Sharding**: Implement queue sharding for horizontal scaling
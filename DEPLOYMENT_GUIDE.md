# Redis Queue Deployment Guide

This guide provides instructions for deploying the new Redis-based queue implementation to production.

## Prerequisites

- Redis server (version 5.0 or higher)
- Python 3.7 or higher
- redis-py library (version 4.0 or higher)

## Deployment Steps

Since the queue is empty, we can deploy the new implementation directly without a migration process.

### 1. Backup Current Code

```bash
# Create a backup of the current code
cp -r /path/to/bot_logic /path/to/bot_logic_backup
```

### 2. Deploy New Files

Copy the following files to your production environment:

- `bot_logic/services/redis_queue_manager.py` - The new Redis queue manager
- `bot_logic/services/chat_api_queue.py` - The updated chat API queue implementation

### 3. Restart Services

Restart the bot-logic service to apply the changes:

```bash
# If using Docker
docker-compose restart bot-logic

# If using systemd
sudo systemctl restart bot-logic

# If running directly
kill -TERM <pid>  # Kill the current process
nohup python bot_logic.py &  # Start a new process
```

### 4. Verify Deployment

Monitor the logs to ensure the service starts correctly and processes messages:

```bash
# If using Docker
docker-compose logs -f bot-logic

# If using systemd
sudo journalctl -u bot-logic -f

# If running directly
tail -f nohup.out
```

Look for the following log messages:

```
INFO - Initialized Redis connection
INFO - Started chat API queue processor
```

### 5. Test Functionality

Send a test message to verify that the queue is working correctly:

1. Use your normal testing process to send a message that triggers the chat API
2. Check the logs to ensure the message is processed correctly
3. Verify that the response is received

### 6. Rollback Plan (If Needed)

If issues are encountered, you can quickly roll back to the previous implementation:

```bash
# Restore the backup files
cp /path/to/bot_logic_backup/services/chat_api_queue.py /path/to/bot_logic/services/

# Restart the service
docker-compose restart bot-logic  # If using Docker
sudo systemctl restart bot-logic  # If using systemd
```

## Monitoring

Monitor the following metrics to ensure the queue is functioning correctly:

- Queue length: Check the number of messages in the queue
- Processing time: Monitor how long it takes to process messages
- Error rate: Track the number of messages that fail processing

You can use the following Redis commands to monitor the queue:

```bash
# Get main queue length
redis-cli zcard chat_api:queue:main

# Get retry queue length
redis-cli zcard chat_api:queue:retry

# Get dead letter queue length
redis-cli zcard chat_api:queue:dlq

# Get queue statistics
redis-cli hgetall chat_api:stats
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
   - Manually release locks if needed:
     ```bash
     redis-cli del chat_api:lock:global_lock
     ```

3. **High Memory Usage**:
   - Reduce TTL for queue items
   - Implement periodic cleanup of old messages
   - Monitor Redis memory usage:
     ```bash
     redis-cli info memory
     ```

### Debugging

Enable debug logging to see detailed queue operations:

```python
import logging
logging.getLogger('bot_logic').setLevel(logging.DEBUG)
```

## Performance Tuning

If you encounter performance issues, consider the following adjustments:

1. **Increase Worker Count**: Run multiple instances of the bot-logic service
2. **Adjust Redis Connection Pool**: Increase the max_connections parameter
3. **Optimize Lock Timeouts**: Reduce lock expiry times for faster processing
4. **Tune Retry Parameters**: Adjust retry delay and max retries based on your needs

## Contact

If you encounter any issues during deployment, please contact the development team.
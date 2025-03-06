#!/bin/bash

echo "System Status:"
echo "--------------"
echo "Current time: $(date)"
echo "Instance: $INSTANCE_NAME"
echo "Hostname: $(hostname)"
echo "Redis connection: $REDIS_HOST:$REDIS_PORT"
echo "API endpoint: $API_CHAT_URL"

# Check Redis connectivity
if redis-cli -h $REDIS_HOST -p $REDIS_PORT -a "$REDIS_PASSWORD" ping | grep -q "PONG"; then
  echo "Redis: Connected ✅"
else
  echo "Redis: Connection failed ❌"
fi

# Print system resources
echo
echo "System Resources:"
echo "Memory Usage: $(free -h | awk '/^Mem:/ {print $3 " used out of " $2}')"
echo "CPU Load: $(uptime | awk '{print $(NF-2), $(NF-1), $(NF)}')"
echo "Disk Usage: $(df -h / | awk 'NR==2 {print $5 " used"}')"

# Print optional message about queued commands
echo
echo "The system supports message queueing."
echo "If you send multiple commands while one is being processed,"
echo "they will be queued and processed sequentially."

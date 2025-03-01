#!/bin/bash

echo "=== System Status ==="
echo "Date and time: $(date)"
echo "Hostname: $(hostname)"
echo "Uptime: $(uptime)"
echo "Memory usage:"
free -h
echo "Disk usage:"
df -h | grep -v tmpfs
echo "Process list:"
ps aux | head -10
echo "===================="

import time

# Service status singleton
class ServiceStatus:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceStatus, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the service status."""
        self.status = {
            "redis_connected": False,
            "messages_processed": 0,
            "responses_sent": 0,
            "errors": 0,
            "last_error": None,
            "last_activity": time.time(),
            "startup_phase": True
        }
    
    def update_activity(self):
        """Update the last activity timestamp."""
        self.status["last_activity"] = time.time()
    
    def record_error(self, error):
        """Record an error in the service status."""
        self.status["errors"] += 1
        self.status["last_error"] = str(error)
        self.update_activity()
    
    def set_redis_status(self, connected):
        """Set the Redis connection status."""
        self.status["redis_connected"] = connected
        self.update_activity()
    
    def increment_messages(self):
        """Increment the messages processed counter."""
        self.status["messages_processed"] += 1
        self.update_activity()
    
    def increment_responses(self):
        """Increment the responses sent counter."""
        self.status["responses_sent"] += 1
        self.update_activity()
    
    def complete_startup(self):
        """Mark the startup phase as complete."""
        self.status["startup_phase"] = False
        self.update_activity()
    
    def get_status(self):
        """Get the current service status."""
        return self.status.copy()

# Create a global instance
service_status = ServiceStatus()
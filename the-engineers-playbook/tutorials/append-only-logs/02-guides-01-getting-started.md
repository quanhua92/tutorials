# Getting Started: Building Your First Append-Only Log

## Introduction: A Simple Event Logger

Let's build a practical append-only log system from scratch. We'll create a simple file-based event logger that demonstrates the core principles while being immediately useful. Think of this as building a digital diary that never forgets anything.

## Prerequisites

### Required Tools
- Basic programming knowledge (we'll use Python for simplicity)
- Text editor or IDE
- Command line access
- Basic understanding of file systems

### What We'll Build
A simple event logging system that:
- Appends events to a log file
- Never modifies existing entries
- Provides basic querying capabilities
- Demonstrates log rotation and basic compaction

## Step 1: The Basic Log Structure

### Creating Our First Log Entry

Let's start with the simplest possible log entry format:

```python
import time
import json
from datetime import datetime
from pathlib import Path

class SimpleLog:
    def __init__(self, log_file="events.log"):
        self.log_file = Path(log_file)
        self.log_file.touch()  # Create if it doesn't exist
    
    def append(self, event_type, data):
        """Append an event to the log"""
        timestamp = int(time.time() * 1000)  # milliseconds
        entry = {
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp/1000).isoformat(),
            "event_type": event_type,
            "data": data
        }
        
        # Convert to JSON and append to file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        
        return timestamp
```

### Your First Log Entries

Create a file called `simple_log.py` and add the code above, then try it out:

```python
# Create a new log
log = SimpleLog("my_events.log")

# Add some events
log.append("user_login", {"user_id": 123, "username": "alice"})
log.append("page_view", {"user_id": 123, "page": "/dashboard"})
log.append("user_logout", {"user_id": 123, "session_duration": 1800})

print("Events logged successfully!")
```

Run this code and check the `my_events.log` file. You should see something like:

```json
{"timestamp": 1705123456789, "datetime": "2024-01-13T10:30:56.789", "event_type": "user_login", "data": {"user_id": 123, "username": "alice"}}
{"timestamp": 1705123456790, "datetime": "2024-01-13T10:30:56.790", "event_type": "page_view", "data": {"user_id": 123, "page": "/dashboard"}}
{"timestamp": 1705123456791, "datetime": "2024-01-13T10:30:56.791", "event_type": "user_logout", "data": {"user_id": 123, "session_duration": 1800}}
```

**Congratulations!** You just created your first append-only log.

## Step 2: Reading from the Log

### Basic Log Reader

Now let's add the ability to read from our log:

```python
class SimpleLog:
    # ... previous code ...
    
    def read_all(self):
        """Read all entries from the log"""
        entries = []
        
        if not self.log_file.exists():
            return entries
        
        with open(self.log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        
        return entries
    
    def read_by_type(self, event_type):
        """Read entries of a specific type"""
        all_entries = self.read_all()
        return [entry for entry in all_entries if entry['event_type'] == event_type]
    
    def read_by_time_range(self, start_time, end_time):
        """Read entries within a time range"""
        all_entries = self.read_all()
        return [
            entry for entry in all_entries 
            if start_time <= entry['timestamp'] <= end_time
        ]
```

### Testing Our Reader

```python
# Read all events
all_events = log.read_all()
print(f"Total events: {len(all_events)}")

# Read specific event types
login_events = log.read_by_type("user_login")
print(f"Login events: {len(login_events)}")

# Read events in a time range
now = int(time.time() * 1000)
one_hour_ago = now - (60 * 60 * 1000)
recent_events = log.read_by_time_range(one_hour_ago, now)
print(f"Recent events: {len(recent_events)}")
```

## Step 3: A Real-World Example

### Web Server Access Log

Let's create a more realistic example—a web server access log:

```python
import random
from datetime import datetime, timedelta

class WebServerLog:
    def __init__(self, log_file="access.log"):
        self.log = SimpleLog(log_file)
    
    def log_request(self, method, path, status_code, response_time_ms, user_agent=None):
        """Log a web request"""
        data = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            "user_agent": user_agent
        }
        return self.log.append("http_request", data)
    
    def log_error(self, error_type, message, stack_trace=None):
        """Log an error"""
        data = {
            "error_type": error_type,
            "message": message,
            "stack_trace": stack_trace
        }
        return self.log.append("error", data)
    
    def get_error_count(self):
        """Get total number of errors"""
        return len(self.log.read_by_type("error"))
    
    def get_response_time_stats(self):
        """Calculate response time statistics"""
        requests = self.log.read_by_type("http_request")
        if not requests:
            return {"avg": 0, "min": 0, "max": 0, "count": 0}
        
        times = [req["data"]["response_time_ms"] for req in requests]
        return {
            "avg": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
            "count": len(times)
        }
```

### Simulating Web Traffic

```python
# Create a web server log
web_log = WebServerLog("web_access.log")

# Simulate some web traffic
endpoints = ["/", "/api/users", "/api/orders", "/dashboard", "/login"]
methods = ["GET", "POST", "PUT", "DELETE"]
status_codes = [200, 201, 404, 500]

for _ in range(100):
    endpoint = random.choice(endpoints)
    method = random.choice(methods)
    status = random.choice(status_codes)
    response_time = random.randint(10, 500)
    
    web_log.log_request(method, endpoint, status, response_time, "Mozilla/5.0")
    
    # Occasionally log an error
    if random.random() < 0.1:
        web_log.log_error("DatabaseError", "Connection timeout", "stack trace here")

# Analyze the logs
print(f"Total errors: {web_log.get_error_count()}")
print(f"Response time stats: {web_log.get_response_time_stats()}")
```

## Step 4: Adding Log Rotation

### Why Log Rotation?

As logs grow, single files become unwieldy. Log rotation creates new files based on size or time, implementing the "segments" concept we learned about.

```python
class RotatingLog:
    def __init__(self, base_name="events", max_size_mb=10):
        self.base_name = base_name
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.current_file_index = 0
        self.current_log = SimpleLog(self._get_current_filename())
    
    def _get_current_filename(self):
        """Get the current log filename"""
        return f"{self.base_name}.{self.current_file_index:06d}.log"
    
    def _should_rotate(self):
        """Check if we should rotate to a new file"""
        current_file = Path(self._get_current_filename())
        return current_file.exists() and current_file.stat().st_size > self.max_size_bytes
    
    def _rotate(self):
        """Rotate to a new log file"""
        self.current_file_index += 1
        self.current_log = SimpleLog(self._get_current_filename())
        print(f"Rotated to new log file: {self._get_current_filename()}")
    
    def append(self, event_type, data):
        """Append an event, rotating if necessary"""
        if self._should_rotate():
            self._rotate()
        
        return self.current_log.append(event_type, data)
    
    def read_all_files(self):
        """Read entries from all log files"""
        all_entries = []
        
        # Read from all rotated files
        for i in range(self.current_file_index + 1):
            filename = f"{self.base_name}.{i:06d}.log"
            if Path(filename).exists():
                log = SimpleLog(filename)
                all_entries.extend(log.read_all())
        
        # Sort by timestamp
        all_entries.sort(key=lambda x: x['timestamp'])
        return all_entries
```

### Testing Log Rotation

```python
# Create a rotating log with tiny size for testing
rotating_log = RotatingLog("test_rotate", max_size_mb=0.001)  # 1KB for testing

# Add enough events to trigger rotation
for i in range(50):
    rotating_log.append("test_event", {"counter": i, "message": f"Event {i}"})

# Read all events across all files
all_events = rotating_log.read_all_files()
print(f"Total events across all files: {len(all_events)}")

# List created files
import glob
log_files = glob.glob("test_rotate.*.log")
print(f"Created {len(log_files)} log files: {log_files}")
```

## Step 5: Basic Compaction

### Simple Compaction Strategy

Let's implement a simple compaction strategy that removes duplicate events and keeps only the latest version:

```python
class CompactingLog:
    def __init__(self, base_name="events"):
        self.base_name = base_name
        self.rotating_log = RotatingLog(base_name)
    
    def append(self, event_type, data):
        """Append an event"""
        return self.rotating_log.append(event_type, data)
    
    def compact_by_key(self, key_field):
        """Compact log by keeping only the latest entry for each key"""
        all_entries = self.rotating_log.read_all_files()
        
        # Group by key, keeping only the latest entry for each key
        key_to_latest = {}
        for entry in all_entries:
            if key_field in entry.get("data", {}):
                key = entry["data"][key_field]
                if key not in key_to_latest or entry["timestamp"] > key_to_latest[key]["timestamp"]:
                    key_to_latest[key] = entry
        
        # Create compacted log
        compacted_filename = f"{self.base_name}.compacted.log"
        compacted_log = SimpleLog(compacted_filename)
        
        # Write compacted entries (sorted by timestamp)
        compacted_entries = sorted(key_to_latest.values(), key=lambda x: x["timestamp"])
        for entry in compacted_entries:
            with open(compacted_filename, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        
        print(f"Compacted {len(all_entries)} entries to {len(compacted_entries)} entries")
        return compacted_filename
```

### Testing Compaction

```python
# Create a compacting log
compact_log = CompactingLog("user_events")

# Add some user events with updates
compact_log.append("user_created", {"user_id": 123, "name": "Alice"})
compact_log.append("user_updated", {"user_id": 123, "email": "alice@old.com"})
compact_log.append("user_updated", {"user_id": 123, "email": "alice@new.com"})
compact_log.append("user_created", {"user_id": 456, "name": "Bob"})
compact_log.append("user_updated", {"user_id": 123, "phone": "555-0123"})

# Compact by user_id
compacted_file = compact_log.compact_by_key("user_id")

# Read compacted results
compacted_log_reader = SimpleLog(compacted_file)
compacted_entries = compacted_log_reader.read_all()

print("Compacted entries:")
for entry in compacted_entries:
    print(f"  {entry['event_type']}: {entry['data']}")
```

## Step 6: A Complete Example Application

### Event-Driven User Management System

Let's build a complete example that demonstrates append-only logs in action:

```python
class UserManagementSystem:
    def __init__(self, log_file="user_system.log"):
        self.log = SimpleLog(log_file)
        self.users = {}  # In-memory state
        self._replay_log()  # Build state from log
    
    def _replay_log(self):
        """Rebuild state from log entries"""
        entries = self.log.read_all()
        for entry in entries:
            self._apply_event(entry)
    
    def _apply_event(self, entry):
        """Apply a single event to update state"""
        event_type = entry["event_type"]
        data = entry["data"]
        
        if event_type == "user_created":
            self.users[data["user_id"]] = {
                "user_id": data["user_id"],
                "name": data["name"],
                "email": data.get("email"),
                "created_at": entry["timestamp"]
            }
        elif event_type == "user_updated":
            user_id = data["user_id"]
            if user_id in self.users:
                self.users[user_id].update(data)
        elif event_type == "user_deleted":
            user_id = data["user_id"]
            if user_id in self.users:
                del self.users[user_id]
    
    def create_user(self, user_id, name, email=None):
        """Create a new user"""
        data = {"user_id": user_id, "name": name}
        if email:
            data["email"] = email
        
        self.log.append("user_created", data)
        self._apply_event({
            "event_type": "user_created",
            "data": data,
            "timestamp": int(time.time() * 1000)
        })
    
    def update_user(self, user_id, **updates):
        """Update a user"""
        data = {"user_id": user_id, **updates}
        self.log.append("user_updated", data)
        self._apply_event({
            "event_type": "user_updated",
            "data": data,
            "timestamp": int(time.time() * 1000)
        })
    
    def delete_user(self, user_id):
        """Delete a user"""
        data = {"user_id": user_id}
        self.log.append("user_deleted", data)
        self._apply_event({
            "event_type": "user_deleted",
            "data": data,
            "timestamp": int(time.time() * 1000)
        })
    
    def get_user(self, user_id):
        """Get current user state"""
        return self.users.get(user_id)
    
    def get_all_users(self):
        """Get all current users"""
        return dict(self.users)
    
    def get_user_history(self, user_id):
        """Get complete history for a user"""
        entries = self.log.read_all()
        return [
            entry for entry in entries
            if entry["data"].get("user_id") == user_id
        ]
```

### Testing the Complete System

```python
# Create user management system
user_system = UserManagementSystem("user_demo.log")

# Create users
user_system.create_user(123, "Alice", "alice@example.com")
user_system.create_user(456, "Bob", "bob@example.com")

# Update users
user_system.update_user(123, email="alice@newemail.com")
user_system.update_user(123, phone="555-0123")
user_system.update_user(456, name="Robert")

# Check current state
print("Current users:")
for user_id, user in user_system.get_all_users().items():
    print(f"  {user_id}: {user}")

# Check user history
print("\nAlice's history:")
alice_history = user_system.get_user_history(123)
for event in alice_history:
    print(f"  {event['datetime']}: {event['event_type']} - {event['data']}")

# Delete a user
user_system.delete_user(456)

print(f"\nUsers after deletion: {list(user_system.get_all_users().keys())}")
```

## Step 7: Running and Experimenting

### Complete Working Example

Save this complete example as `append_log_demo.py`:

```python
#!/usr/bin/env python3

import time
import json
from datetime import datetime
from pathlib import Path

# ... (include all the classes from above) ...

def main():
    print("=== Append-Only Log Demo ===")
    
    # Demo 1: Basic logging
    print("\n1. Basic Logging Demo")
    log = SimpleLog("demo_basic.log")
    
    log.append("system_start", {"version": "1.0.0"})
    log.append("user_login", {"user_id": 123, "username": "alice"})
    log.append("data_processed", {"records": 1000, "duration_ms": 150})
    
    entries = log.read_all()
    print(f"Logged {len(entries)} events")
    
    # Demo 2: Web server logging
    print("\n2. Web Server Logging Demo")
    web_log = WebServerLog("demo_web.log")
    
    # Simulate traffic
    for i in range(10):
        web_log.log_request("GET", f"/api/endpoint{i}", 200, i * 10)
    
    stats = web_log.get_response_time_stats()
    print(f"Response time stats: {stats}")
    
    # Demo 3: Log rotation
    print("\n3. Log Rotation Demo")
    rotating_log = RotatingLog("demo_rotate", max_size_mb=0.001)
    
    for i in range(20):
        rotating_log.append("counter_event", {"value": i})
    
    all_events = rotating_log.read_all_files()
    print(f"Total events across rotated files: {len(all_events)}")
    
    # Demo 4: User management system
    print("\n4. User Management System Demo")
    user_system = UserManagementSystem("demo_users.log")
    
    user_system.create_user(1, "Alice")
    user_system.create_user(2, "Bob")
    user_system.update_user(1, email="alice@example.com")
    user_system.update_user(1, phone="555-0123")
    
    print(f"Current users: {list(user_system.get_all_users().keys())}")
    
    alice_history = user_system.get_user_history(1)
    print(f"Alice has {len(alice_history)} events in history")
    
    print("\n=== Demo Complete ===")

if __name__ == "__main__":
    main()
```

### Run the Demo

```bash
python append_log_demo.py
```

You should see output like:

```
=== Append-Only Log Demo ===

1. Basic Logging Demo
Logged 3 events

2. Web Server Logging Demo
Response time stats: {'avg': 45.0, 'min': 0, 'max': 90, 'count': 10}

3. Log Rotation Demo
Rotated to new log file: demo_rotate.000001.log
Rotated to new log file: demo_rotate.000002.log
Total events across rotated files: 20

4. User Management System Demo
Current users: [1, 2]
Alice has 3 events in history

=== Demo Complete ===
```

## Step 8: Key Takeaways

### What You've Learned

1. **Append-Only Principle**: Data is never modified, only added
2. **Event-Driven Architecture**: Store events, derive state
3. **Log Rotation**: Manage file sizes through segmentation
4. **Compaction**: Remove redundant data while preserving history
5. **State Reconstruction**: Rebuild current state from event history

### Why This Matters

The simple system you just built demonstrates the core principles used in:

- **Apache Kafka**: Distributed event streaming
- **Event Sourcing**: Application architecture pattern
- **Database Transaction Logs**: Ensuring data consistency
- **Git**: Version control system
- **Blockchain**: Immutable transaction ledger

### Next Steps

Try these experiments:

1. **Add compression**: Compress old log files to save space
2. **Add indexing**: Create index files for faster queries
3. **Add replication**: Write to multiple log files simultaneously
4. **Add network support**: Send events over HTTP/TCP
5. **Add different serialization**: Use binary formats instead of JSON

### Performance Considerations

Your simple implementation is educational but not production-ready. For real systems, consider:

- **Batch writes**: Group multiple events into single writes
- **Buffer management**: Use memory buffers for better performance
- **Concurrent access**: Handle multiple readers/writers safely
- **Error handling**: Robust error recovery and validation
- **Monitoring**: Track metrics like throughput and latency

## Conclusion

You've built a working append-only log system that demonstrates the fundamental concepts. While simple, this system shows how append-only logs can transform complex data management problems into straightforward sequential operations.

The key insight is that by embracing immutability and focusing on events rather than state, we can build systems that are simpler, more reliable, and easier to reason about. This is the foundation of modern distributed systems and event-driven architectures.

In the next section, we'll dive deeper into how to reconstruct application state from these event logs—the bridge between immutable events and mutable application state.
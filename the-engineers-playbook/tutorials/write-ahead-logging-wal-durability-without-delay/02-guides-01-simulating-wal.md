# Simulating WAL: A Hands-On Python Implementation

Let's build a simple but functional Write-Ahead Logging system in Python. This implementation will demonstrate the core concepts through working code that you can run and experiment with.

## The Scenario

We'll create a simple key-value database that supports:
- PUT operations to store key-value pairs
- GET operations to retrieve values
- Transactional durability through WAL
- Crash recovery from the log

## Project Structure

Create a new directory and the following files:

```
wal_demo/
├── wal_database.py      # Main database implementation
├── test_database.py     # Test scenarios
└── crash_simulator.py   # Simulates crashes and recovery
```

## Core WAL Database Implementation

Let's start with the main database class:

```python
# wal_database.py
import json
import os
import time
import threading
from typing import Dict, List, Optional, Any
import hashlib

class WALEntry:
    """Represents a single Write-Ahead Log entry"""
    
    def __init__(self, lsn: int, transaction_id: str, operation: str, 
                 key: str = None, old_value: Any = None, new_value: Any = None):
        self.lsn = lsn  # Log Sequence Number
        self.transaction_id = transaction_id
        self.operation = operation  # PUT, DELETE, COMMIT, ROLLBACK
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.timestamp = time.time()
        self.checksum = self._calculate_checksum()
    
    def _calculate_checksum(self) -> str:
        """Calculate checksum to detect corruption"""
        data = f"{self.lsn}{self.transaction_id}{self.operation}{self.key}{self.new_value}"
        return hashlib.md5(data.encode()).hexdigest()[:8]
    
    def to_dict(self) -> Dict:
        """Serialize entry for writing to log"""
        return {
            'lsn': self.lsn,
            'transaction_id': self.transaction_id,
            'operation': self.operation,
            'key': self.key,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'timestamp': self.timestamp,
            'checksum': self.checksum
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'WALEntry':
        """Deserialize entry from log"""
        entry = cls(
            lsn=data['lsn'],
            transaction_id=data['transaction_id'],
            operation=data['operation'],
            key=data.get('key'),
            old_value=data.get('old_value'),
            new_value=data.get('new_value')
        )
        entry.timestamp = data['timestamp']
        entry.checksum = data['checksum']
        return entry
    
    def is_valid(self) -> bool:
        """Verify entry hasn't been corrupted"""
        return self.checksum == self._calculate_checksum()

class Transaction:
    """Represents a database transaction"""
    
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self.operations: List[WALEntry] = []
        self.is_committed = False
        self.is_rolled_back = False
    
    def add_operation(self, entry: WALEntry):
        """Add an operation to this transaction"""
        self.operations.append(entry)

class WALDatabase:
    """A simple key-value database with Write-Ahead Logging"""
    
    def __init__(self, data_file: str = "database.json", log_file: str = "wal.log"):
        self.data_file = data_file
        self.log_file = log_file
        self.data: Dict[str, Any] = {}
        self.transactions: Dict[str, Transaction] = {}
        self.next_lsn = 1
        self.next_transaction_id = 1
        self.lock = threading.Lock()
        
        # Load existing data and recover from log
        self._load_data()
        self._recover_from_log()
    
    def _load_data(self):
        """Load existing data from disk"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    self.data = json.load(f)
                print(f"Loaded {len(self.data)} items from {self.data_file}")
            except Exception as e:
                print(f"Error loading data file: {e}")
                self.data = {}
    
    def _save_data(self):
        """Save current data to disk (background operation)"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving data file: {e}")
    
    def _write_log_entry(self, entry: WALEntry):
        """Write entry to WAL (synchronous, with fsync)"""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
                f.flush()
                os.fsync(f.fileno())  # Force to disk
        except Exception as e:
            print(f"Error writing to log: {e}")
            raise
    
    def _recover_from_log(self):
        """Recover database state from WAL"""
        if not os.path.exists(self.log_file):
            print("No WAL file found, starting fresh")
            return
        
        print("Starting recovery from WAL...")
        committed_transactions = set()
        all_operations = []
        
        # First pass: Find all committed transactions
        try:
            with open(self.log_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        entry_data = json.loads(line.strip())
                        entry = WALEntry.from_dict(entry_data)
                        
                        if not entry.is_valid():
                            print(f"WARNING: Corrupted entry at line {line_num}, stopping recovery")
                            break
                        
                        all_operations.append(entry)
                        
                        if entry.operation == 'COMMIT':
                            committed_transactions.add(entry.transaction_id)
                        
                        # Update LSN counter
                        self.next_lsn = max(self.next_lsn, entry.lsn + 1)
                        
                    except json.JSONDecodeError:
                        print(f"WARNING: Invalid JSON at line {line_num}, stopping recovery")
                        break
        except Exception as e:
            print(f"Error during recovery: {e}")
            return
        
        # Second pass: Apply all operations from committed transactions
        operations_applied = 0
        for entry in all_operations:
            if entry.transaction_id in committed_transactions and entry.operation in ['PUT', 'DELETE']:
                if entry.operation == 'PUT':
                    self.data[entry.key] = entry.new_value
                elif entry.operation == 'DELETE':
                    self.data.pop(entry.key, None)
                operations_applied += 1
        
        print(f"Recovery complete: {len(committed_transactions)} committed transactions, "
              f"{operations_applied} operations applied")
    
    def begin_transaction(self) -> str:
        """Start a new transaction"""
        with self.lock:
            transaction_id = f"TXN-{self.next_transaction_id:06d}"
            self.next_transaction_id += 1
            self.transactions[transaction_id] = Transaction(transaction_id)
            print(f"Started transaction {transaction_id}")
            return transaction_id
    
    def put(self, transaction_id: str, key: str, value: Any):
        """Store a key-value pair within a transaction"""
        with self.lock:
            if transaction_id not in self.transactions:
                raise ValueError(f"Transaction {transaction_id} not found")
            
            transaction = self.transactions[transaction_id]
            if transaction.is_committed or transaction.is_rolled_back:
                raise ValueError(f"Transaction {transaction_id} is already finished")
            
            # Get old value for rollback purposes
            old_value = self.data.get(key)
            
            # Create and write WAL entry
            entry = WALEntry(
                lsn=self.next_lsn,
                transaction_id=transaction_id,
                operation='PUT',
                key=key,
                old_value=old_value,
                new_value=value
            )
            
            self._write_log_entry(entry)
            transaction.add_operation(entry)
            self.next_lsn += 1
            
            print(f"PUT {key}={value} logged in {transaction_id} (LSN-{entry.lsn})")
    
    def delete(self, transaction_id: str, key: str):
        """Delete a key within a transaction"""
        with self.lock:
            if transaction_id not in self.transactions:
                raise ValueError(f"Transaction {transaction_id} not found")
            
            transaction = self.transactions[transaction_id]
            if transaction.is_committed or transaction.is_rolled_back:
                raise ValueError(f"Transaction {transaction_id} is already finished")
            
            old_value = self.data.get(key)
            if old_value is None:
                raise KeyError(f"Key {key} not found")
            
            entry = WALEntry(
                lsn=self.next_lsn,
                transaction_id=transaction_id,
                operation='DELETE',
                key=key,
                old_value=old_value,
                new_value=None
            )
            
            self._write_log_entry(entry)
            transaction.add_operation(entry)
            self.next_lsn += 1
            
            print(f"DELETE {key} logged in {transaction_id} (LSN-{entry.lsn})")
    
    def commit(self, transaction_id: str):
        """Commit a transaction, making all changes durable"""
        with self.lock:
            if transaction_id not in self.transactions:
                raise ValueError(f"Transaction {transaction_id} not found")
            
            transaction = self.transactions[transaction_id]
            if transaction.is_committed:
                print(f"Transaction {transaction_id} already committed")
                return
            
            # Write commit record to log
            commit_entry = WALEntry(
                lsn=self.next_lsn,
                transaction_id=transaction_id,
                operation='COMMIT'
            )
            
            self._write_log_entry(commit_entry)
            self.next_lsn += 1
            
            # Apply all transaction operations to in-memory data
            for operation in transaction.operations:
                if operation.operation == 'PUT':
                    self.data[operation.key] = operation.new_value
                elif operation.operation == 'DELETE':
                    self.data.pop(operation.key, None)
            
            transaction.is_committed = True
            print(f"Transaction {transaction_id} committed (LSN-{commit_entry.lsn})")
            
            # Asynchronously save data to disk (optional optimization)
            threading.Thread(target=self._save_data, daemon=True).start()
    
    def rollback(self, transaction_id: str):
        """Rollback a transaction, discarding all changes"""
        with self.lock:
            if transaction_id not in self.transactions:
                raise ValueError(f"Transaction {transaction_id} not found")
            
            transaction = self.transactions[transaction_id]
            if transaction.is_rolled_back:
                print(f"Transaction {transaction_id} already rolled back")
                return
            
            # Write rollback record to log
            rollback_entry = WALEntry(
                lsn=self.next_lsn,
                transaction_id=transaction_id,
                operation='ROLLBACK'
            )
            
            self._write_log_entry(rollback_entry)
            self.next_lsn += 1
            
            transaction.is_rolled_back = True
            print(f"Transaction {transaction_id} rolled back (LSN-{rollback_entry.lsn})")
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value by key (reads committed data)"""
        with self.lock:
            return self.data.get(key)
    
    def list_all(self) -> Dict[str, Any]:
        """Get all key-value pairs"""
        with self.lock:
            return self.data.copy()
    
    def get_log_stats(self) -> Dict:
        """Get statistics about the WAL"""
        if not os.path.exists(self.log_file):
            return {"entries": 0, "size_bytes": 0}
        
        entries = 0
        with open(self.log_file, 'r') as f:
            for _ in f:
                entries += 1
        
        size = os.path.getsize(self.log_file)
        return {"entries": entries, "size_bytes": size}
```

## Testing the WAL Database

Now let's create comprehensive tests:

```python
# test_database.py
import os
import time
from wal_database import WALDatabase

def test_basic_operations():
    """Test basic PUT/GET operations with transactions"""
    print("=== Test: Basic Operations ===")
    
    # Clean up from previous runs
    for file in ["database.json", "wal.log"]:
        if os.path.exists(file):
            os.remove(file)
    
    db = WALDatabase()
    
    # Transaction 1: Add some data
    txn1 = db.begin_transaction()
    db.put(txn1, "user:1", {"name": "Alice", "balance": 1000})
    db.put(txn1, "user:2", {"name": "Bob", "balance": 500})
    db.commit(txn1)
    
    # Verify data is available
    assert db.get("user:1")["name"] == "Alice"
    assert db.get("user:2")["balance"] == 500
    
    print("✅ Basic operations test passed")

def test_rollback():
    """Test transaction rollback"""
    print("\n=== Test: Rollback ===")
    
    db = WALDatabase()
    original_data = db.list_all().copy()
    
    # Start transaction and make changes
    txn = db.begin_transaction()
    db.put(txn, "temp:1", "should_not_persist")
    db.put(txn, "temp:2", "should_also_not_persist")
    
    # Rollback instead of commit
    db.rollback(txn)
    
    # Verify data hasn't changed
    assert db.list_all() == original_data
    assert db.get("temp:1") is None
    
    print("✅ Rollback test passed")

def test_crash_recovery():
    """Test recovery after simulated crash"""
    print("\n=== Test: Crash Recovery ===")
    
    # Part 1: Create data and "crash" before background save
    db1 = WALDatabase()
    
    txn1 = db1.begin_transaction()
    db1.put(txn1, "crash:test", "survived_crash")
    db1.commit(txn1)
    
    # Simulate crash by deleting the data file but keeping the log
    if os.path.exists("database.json"):
        os.remove("database.json")
    
    # Part 2: Recovery - create new database instance
    db2 = WALDatabase()
    
    # Verify data was recovered from log
    assert db2.get("crash:test") == "survived_crash"
    
    print("✅ Crash recovery test passed")

def test_partial_transaction():
    """Test recovery with uncommitted transactions"""
    print("\n=== Test: Partial Transaction Recovery ===")
    
    db = WALDatabase()
    
    # Committed transaction
    txn1 = db.begin_transaction()
    db.put(txn1, "committed:data", "should_survive")
    db.commit(txn1)
    
    # Uncommitted transaction (simulates crash before commit)
    txn2 = db.begin_transaction()
    db.put(txn2, "uncommitted:data", "should_not_survive")
    # Note: No commit() call - simulates crash
    
    # Force recovery by creating new database instance
    db2 = WALDatabase()
    
    # Verify only committed data survived
    assert db2.get("committed:data") == "should_survive"
    assert db2.get("uncommitted:data") is None
    
    print("✅ Partial transaction test passed")

def test_concurrent_transactions():
    """Test multiple concurrent transactions"""
    print("\n=== Test: Concurrent Transactions ===")
    
    db = WALDatabase()
    
    # Start multiple transactions
    txn1 = db.begin_transaction()
    txn2 = db.begin_transaction()
    txn3 = db.begin_transaction()
    
    # Make changes in different transactions
    db.put(txn1, "concurrent:1", "from_txn1")
    db.put(txn2, "concurrent:2", "from_txn2")
    db.put(txn3, "concurrent:3", "from_txn3")
    
    # Commit in different order
    db.commit(txn2)
    db.rollback(txn3)  # This one gets rolled back
    db.commit(txn1)
    
    # Verify final state
    assert db.get("concurrent:1") == "from_txn1"
    assert db.get("concurrent:2") == "from_txn2"
    assert db.get("concurrent:3") is None  # Rolled back
    
    print("✅ Concurrent transactions test passed")

if __name__ == "__main__":
    test_basic_operations()
    test_rollback()
    test_crash_recovery()
    test_partial_transaction()
    test_concurrent_transactions()
    
    print("\n🎉 All tests passed!")
    
    # Show final log statistics
    db = WALDatabase()
    stats = db.get_log_stats()
    print(f"Final WAL stats: {stats['entries']} entries, {stats['size_bytes']} bytes")
```

## Crash Simulator

Let's create a more dramatic crash simulation:

```python
# crash_simulator.py
import os
import signal
import time
import threading
from wal_database import WALDatabase

def simulate_bank_transfer():
    """Simulate a banking system with transfers between accounts"""
    print("=== Banking System Crash Simulation ===")
    
    # Clean slate
    for file in ["database.json", "wal.log"]:
        if os.path.exists(file):
            os.remove(file)
    
    db = WALDatabase()
    
    # Set up initial accounts
    setup_txn = db.begin_transaction()
    db.put(setup_txn, "account:alice", {"name": "Alice", "balance": 1000})
    db.put(setup_txn, "account:bob", {"name": "Bob", "balance": 1000})
    db.put(setup_txn, "account:charlie", {"name": "Charlie", "balance": 1000})
    db.commit(setup_txn)
    
    print("Initial balances:")
    for account in ["account:alice", "account:bob", "account:charlie"]:
        data = db.get(account)
        print(f"  {data['name']}: ${data['balance']}")
    
    # Start multiple transfers
    transfers = []
    
    # Transfer 1: Alice → Bob ($200)
    txn1 = db.begin_transaction()
    alice = db.get("account:alice")
    bob = db.get("account:bob")
    db.put(txn1, "account:alice", {"name": "Alice", "balance": alice["balance"] - 200})
    db.put(txn1, "account:bob", {"name": "Bob", "balance": bob["balance"] + 200})
    transfers.append(("Transfer Alice→Bob $200", txn1))
    
    # Transfer 2: Bob → Charlie ($150)
    txn2 = db.begin_transaction()
    bob = db.get("account:bob")
    charlie = db.get("account:charlie")
    db.put(txn2, "account:bob", {"name": "Bob", "balance": bob["balance"] - 150})
    db.put(txn2, "account:charlie", {"name": "Charlie", "balance": charlie["balance"] + 150})
    transfers.append(("Transfer Bob→Charlie $150", txn2))
    
    # Transfer 3: Charlie → Alice ($75)
    txn3 = db.begin_transaction()
    charlie = db.get("account:charlie")
    alice = db.get("account:alice")
    db.put(txn3, "account:charlie", {"name": "Charlie", "balance": charlie["balance"] - 75})
    db.put(txn3, "account:alice", {"name": "Alice", "balance": alice["balance"] + 75})
    transfers.append(("Transfer Charlie→Alice $75", txn3))
    
    print(f"\nStarted {len(transfers)} transfers...")
    
    # Commit some transfers, simulate crash before others
    db.commit(txn1)  # This completes
    print("✅ Committed: Alice→Bob $200")
    
    # Simulate crash here (txn2 and txn3 never commit)
    print("💥 SYSTEM CRASH! (txn2 and txn3 incomplete)")
    
    # Delete data file to simulate crash
    if os.path.exists("database.json"):
        os.remove("database.json")
    
    # Recovery phase
    print("\n🔄 Starting recovery...")
    recovered_db = WALDatabase()
    
    print("\nBalances after recovery:")
    total_after = 0
    for account in ["account:alice", "account:bob", "account:charlie"]:
        data = recovered_db.get(account)
        print(f"  {data['name']}: ${data['balance']}")
        total_after += data['balance']
    
    print(f"\nTotal money in system: ${total_after} (should be $3000)")
    
    # Verify integrity
    alice_final = recovered_db.get("account:alice")
    bob_final = recovered_db.get("account:bob")
    charlie_final = recovered_db.get("account:charlie")
    
    # Only the first transfer should have been applied
    assert alice_final["balance"] == 800   # 1000 - 200
    assert bob_final["balance"] == 1200    # 1000 + 200  
    assert charlie_final["balance"] == 1000  # Unchanged
    
    print("✅ Recovery successful - only committed transfers survived")

def simulate_high_frequency_crash():
    """Simulate crash during high-frequency operations"""
    print("\n=== High-Frequency Operations Crash Test ===")
    
    # Clean slate
    for file in ["database.json", "wal.log"]:
        if os.path.exists(file):
            os.remove(file)
    
    db = WALDatabase()
    
    # Start multiple threads doing rapid operations
    stop_flag = threading.Event()
    committed_txns = []
    
    def rapid_operations():
        """Worker thread that does rapid database operations"""
        counter = 0
        while not stop_flag.is_set():
            try:
                txn = db.begin_transaction()
                db.put(txn, f"rapid:{counter}", f"value_{counter}")
                db.commit(txn)
                committed_txns.append(f"rapid:{counter}")
                counter += 1
                time.sleep(0.01)  # 100 ops/second
            except Exception as e:
                print(f"Operation failed: {e}")
                break
    
    # Start worker threads
    threads = []
    for i in range(3):
        thread = threading.Thread(target=rapid_operations)
        thread.start()
        threads.append(thread)
    
    # Let them run for a short time
    time.sleep(0.5)
    
    # Simulate crash
    stop_flag.set()
    print(f"💥 CRASH after {len(committed_txns)} committed operations")
    
    # Wait for threads to stop
    for thread in threads:
        thread.join()
    
    # Delete data file
    if os.path.exists("database.json"):
        os.remove("database.json")
    
    # Recovery
    recovered_db = WALDatabase()
    
    # Verify all committed data survived
    recovered_count = 0
    for key in committed_txns:
        if recovered_db.get(key) is not None:
            recovered_count += 1
    
    print(f"Recovery: {recovered_count}/{len(committed_txns)} operations survived")
    assert recovered_count == len(committed_txns)
    print("✅ High-frequency crash test passed")

if __name__ == "__main__":
    simulate_bank_transfer()
    simulate_high_frequency_crash()
    
    print("\n🎉 All crash simulations completed successfully!")
```

## Running the Simulations

Execute the tests and simulations:

```bash
# Run basic functionality tests
python test_database.py

# Run crash simulations
python crash_simulator.py

# Inspect the WAL file
cat wal.log | head -10
```

## Key Insights from the Implementation

### 1. **Sequential Log Writes Are Fast**
Notice how all log operations use `append` mode and `fsync()`. This ensures durability while maintaining performance.

### 2. **Recovery Is Deterministic**
The recovery process follows a precise algorithm:
1. Find all committed transactions
2. Apply their operations in order
3. Ignore uncommitted transactions

### 3. **Durability Before Response**
The `commit()` method doesn't return until the commit record is safely on disk. This guarantees durability.

### 4. **Background Data Updates**
The actual data file updates happen asynchronously. This separates durability (handled by WAL) from performance optimization.

### 5. **Atomicity Through Logging**
All operations in a transaction either survive together (if committed) or disappear together (if not committed).

## Expected Output

When you run the tests, you should see:

```
=== Test: Basic Operations ===
Started transaction TXN-000001
PUT user:1={'name': 'Alice', 'balance': 1000} logged in TXN-000001 (LSN-1)
PUT user:2={'name': 'Bob', 'balance': 500} logged in TXN-000001 (LSN-2)
Transaction TXN-000001 committed (LSN-3)
✅ Basic operations test passed

=== Banking System Crash Simulation ===
Initial balances:
  Alice: $1000
  Bob: $1000
  Charlie: $1000

Started 3 transfers...
✅ Committed: Alice→Bob $200
💥 SYSTEM CRASH! (txn2 and txn3 incomplete)

🔄 Starting recovery...
Recovery complete: 2 committed transactions, 5 operations applied

Balances after recovery:
  Alice: $800
  Bob: $1200
  Charlie: $1000

Total money in system: $3000 (should be $3000)
✅ Recovery successful - only committed transfers survived
```

This implementation demonstrates the core principles of Write-Ahead Logging in a way you can understand, modify, and experiment with. While production databases have additional optimizations (parallel processing, compression, replication), the fundamental concepts remain the same.

The magic is in the separation: durability is provided by simple, fast log writes, while performance is optimized through asynchronous background processing. This separation enables both strong guarantees and excellent performance – the best of both worlds.
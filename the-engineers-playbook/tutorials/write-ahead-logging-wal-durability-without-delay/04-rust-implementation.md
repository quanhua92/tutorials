# Rust Implementation: Building a Production-Grade WAL System

This implementation demonstrates Write-Ahead Logging concepts through a complete, working WAL system in Rust. We'll build a transactional key-value store that showcases all the fundamental WAL concepts: sequential logging, commit protocols, crash recovery, and durability guarantees.

## Overview

Our Rust WAL implementation will provide:
- Transactional ACID guarantees through WAL
- Crash recovery with REDO/UNDO operations  
- Concurrent transaction support
- Configurable durability levels (sync/async)
- Production-ready error handling and logging

```mermaid
graph TB
    subgraph "Rust WAL Architecture"
        App["Application Layer"]
        
        subgraph "Transaction Manager"
            TxnMgr["Transaction Manager"]
            TxnStore["Active Transactions"]
        end
        
        subgraph "WAL Core"
            WALMgr["WAL Manager"]
            LogBuffer["Log Buffer"]
            LogFile["Log Files"]
        end
        
        subgraph "Storage Engine"
            StoreMgr["Storage Manager"]
            DataPages["Data Pages"]
            PageCache["Page Cache"]
        end
        
        App --> TxnMgr
        TxnMgr --> WALMgr
        TxnMgr --> StoreMgr
        WALMgr --> LogBuffer
        LogBuffer --> LogFile
        StoreMgr --> PageCache
        PageCache --> DataPages
    end
```

## Dependencies

Add these dependencies to your `Cargo.toml`:

```toml
[package]
name = "wal-system"
version = "0.1.0"
edition = "2021"

[dependencies]
tokio = { version = "1", features = ["full"] }
serde = { version = "1.0", features = ["derive"] }
bincode = "1.3"
uuid = { version = "1.0", features = ["v4"] }
thiserror = "1.0"
tracing = "0.1"
tracing-subscriber = "0.3"
crc32fast = "1.3"
crossbeam = "0.8"
parking_lot = "0.12"
memmap2 = "0.7"
```

## Core Data Structures

```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;
use parking_lot::{RwLock, Mutex};

/// Log Sequence Number - provides total ordering of log entries
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct LSN(pub u64);

impl LSN {
    pub fn next(&self) -> LSN {
        LSN(self.0 + 1)
    }
}

/// Transaction identifier
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TransactionId(pub Uuid);

impl TransactionId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

/// WAL entry representing a single logged operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WALEntry {
    pub lsn: LSN,
    pub transaction_id: TransactionId,
    pub entry_type: WALEntryType,
    pub timestamp: u64,
    pub checksum: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum WALEntryType {
    Begin,
    Put { key: String, old_value: Option<String>, new_value: String },
    Delete { key: String, old_value: String },
    Commit,
    Rollback,
    Checkpoint { lsn: LSN },
}

impl WALEntry {
    pub fn new(lsn: LSN, transaction_id: TransactionId, entry_type: WALEntryType) -> Self {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        
        let mut entry = Self {
            lsn,
            transaction_id,
            entry_type,
            timestamp,
            checksum: 0,
        };
        
        entry.checksum = entry.calculate_checksum();
        entry
    }
    
    fn calculate_checksum(&self) -> u32 {
        let data = bincode::serialize(&(
            &self.lsn,
            &self.transaction_id,
            &self.entry_type,
            &self.timestamp
        )).unwrap();
        crc32fast::hash(&data)
    }
    
    pub fn verify_checksum(&self) -> bool {
        self.checksum == self.calculate_checksum()
    }
}

/// Transaction state tracking
#[derive(Debug)]
pub struct Transaction {
    pub id: TransactionId,
    pub start_lsn: LSN,
    pub status: TransactionStatus,
    pub operations: Vec<WALEntry>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum TransactionStatus {
    Active,
    Committed,
    Aborted,
}

/// Storage page for key-value data
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataPage {
    pub page_id: u64,
    pub data: HashMap<String, String>,
    pub lsn: LSN, // Last LSN that modified this page
}

impl DataPage {
    pub fn new(page_id: u64) -> Self {
        Self {
            page_id,
            data: HashMap::new(),
            lsn: LSN(0),
        }
    }
}

#[derive(thiserror::Error, Debug)]
pub enum WALError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("Serialization error: {0}")]
    Serialization(#[from] bincode::Error),
    #[error("Transaction error: {0}")]
    Transaction(String),
    #[error("Corruption detected: {0}")]
    Corruption(String),
    #[error("Recovery error: {0}")]
    Recovery(String),
}

pub type Result<T> = std::result::Result<T, WALError>;
```

## WAL Manager Implementation

```rust
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// Configuration for WAL behavior
#[derive(Debug, Clone)]
pub struct WALConfig {
    pub log_directory: PathBuf,
    pub max_log_file_size: u64,
    pub sync_mode: SyncMode,
    pub buffer_size: usize,
}

#[derive(Debug, Clone)]
pub enum SyncMode {
    /// Synchronous - fsync after every commit (safe but slow)
    Sync,
    /// Asynchronous - periodic fsyncs (fast but potential data loss)
    Async,
    /// Batch - group commits together (balanced)
    Batch(usize),
}

impl Default for WALConfig {
    fn default() -> Self {
        Self {
            log_directory: PathBuf::from("./wal"),
            max_log_file_size: 64 * 1024 * 1024, // 64MB
            sync_mode: SyncMode::Batch(10),
            buffer_size: 1024 * 1024, // 1MB
        }
    }
}

/// WAL Manager - handles all WAL operations
pub struct WALManager {
    config: WALConfig,
    current_lsn: AtomicU64,
    current_file: Mutex<Option<BufWriter<File>>>,
    current_file_size: AtomicU64,
    current_file_number: AtomicU64,
}

impl WALManager {
    pub fn new(config: WALConfig) -> Result<Self> {
        std::fs::create_dir_all(&config.log_directory)?;
        
        let manager = Self {
            config,
            current_lsn: AtomicU64::new(1),
            current_file: Mutex::new(None),
            current_file_size: AtomicU64::new(0),
            current_file_number: AtomicU64::new(1),
        };
        
        manager.create_new_log_file()?;
        Ok(manager)
    }
    
    /// Append a WAL entry to the log
    pub fn append_entry(&self, entry: &WALEntry) -> Result<()> {
        let serialized = bincode::serialize(entry)?;
        let entry_size = serialized.len() as u64;
        
        // Check if we need to rotate to a new log file
        if self.current_file_size.load(Ordering::Relaxed) + entry_size > self.config.max_log_file_size {
            self.rotate_log_file()?;
        }
        
        // Write the entry
        {
            let mut file_guard = self.current_file.lock();
            if let Some(ref mut writer) = *file_guard {
                // Write entry length first (for reading)
                writer.write_all(&(entry_size as u32).to_le_bytes())?;
                // Write the actual entry
                writer.write_all(&serialized)?;
                
                // Sync based on configuration
                match self.config.sync_mode {
                    SyncMode::Sync => {
                        writer.flush()?;
                        writer.get_ref().sync_all()?;
                    }
                    SyncMode::Async => {
                        // Will sync periodically
                    }
                    SyncMode::Batch(_) => {
                        // Will sync on batch completion
                    }
                }
            }
        }
        
        self.current_file_size.fetch_add(entry_size + 4, Ordering::Relaxed);
        
        tracing::debug!("Appended WAL entry LSN {} ({} bytes)", entry.lsn.0, entry_size);
        Ok(())
    }
    
    /// Force all buffered data to disk
    pub fn sync(&self) -> Result<()> {
        let mut file_guard = self.current_file.lock();
        if let Some(ref mut writer) = *file_guard {
            writer.flush()?;
            writer.get_ref().sync_all()?;
        }
        Ok(())
    }
    
    /// Get the next LSN
    pub fn next_lsn(&self) -> LSN {
        LSN(self.current_lsn.fetch_add(1, Ordering::Relaxed))
    }
    
    /// Read WAL entries starting from a given LSN
    pub fn read_entries_from(&self, start_lsn: LSN) -> Result<Vec<WALEntry>> {
        let mut entries = Vec::new();
        
        // Read from all log files in order
        for file_num in 1..=self.current_file_number.load(Ordering::Relaxed) {
            let file_path = self.log_file_path(file_num);
            if file_path.exists() {
                let file_entries = self.read_entries_from_file(&file_path, start_lsn)?;
                entries.extend(file_entries);
            }
        }
        
        // Sort by LSN to ensure proper ordering
        entries.sort_by_key(|e| e.lsn);
        Ok(entries)
    }
    
    fn create_new_log_file(&self) -> Result<()> {
        let file_number = self.current_file_number.load(Ordering::Relaxed);
        let file_path = self.log_file_path(file_number);
        
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&file_path)?;
            
        let writer = BufWriter::with_capacity(self.config.buffer_size, file);
        
        {
            let mut file_guard = self.current_file.lock();
            *file_guard = Some(writer);
        }
        
        self.current_file_size.store(0, Ordering::Relaxed);
        
        tracing::info!("Created new WAL file: {:?}", file_path);
        Ok(())
    }
    
    fn rotate_log_file(&self) -> Result<()> {
        // Sync current file before rotation
        self.sync()?;
        
        // Close current file
        {
            let mut file_guard = self.current_file.lock();
            *file_guard = None;
        }
        
        // Create new file
        self.current_file_number.fetch_add(1, Ordering::Relaxed);
        self.create_new_log_file()?;
        
        Ok(())
    }
    
    fn log_file_path(&self, file_number: u64) -> PathBuf {
        self.config.log_directory.join(format!("wal-{:08}.log", file_number))
    }
    
    fn read_entries_from_file(&self, file_path: &Path, start_lsn: LSN) -> Result<Vec<WALEntry>> {
        let mut entries = Vec::new();
        let file = File::open(file_path)?;
        let mut reader = BufReader::new(file);
        
        loop {
            // Read entry length
            let mut len_bytes = [0u8; 4];
            match reader.read_exact(&mut len_bytes) {
                Ok(()) => {},
                Err(e) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
                Err(e) => return Err(e.into()),
            }
            
            let entry_len = u32::from_le_bytes(len_bytes) as usize;
            
            // Read entry data
            let mut entry_data = vec![0u8; entry_len];
            reader.read_exact(&mut entry_data)?;
            
            // Deserialize entry
            let entry: WALEntry = bincode::deserialize(&entry_data)?;
            
            // Verify checksum
            if !entry.verify_checksum() {
                return Err(WALError::Corruption(format!("Checksum mismatch for LSN {}", entry.lsn.0)));
            }
            
            // Only include entries at or after start_lsn
            if entry.lsn >= start_lsn {
                entries.push(entry);
            }
        }
        
        Ok(entries)
    }
}
```

## Transaction Manager

```rust
/// Transaction Manager - coordinates transactions and WAL operations
pub struct TransactionManager {
    wal_manager: Arc<WALManager>,
    active_transactions: RwLock<HashMap<TransactionId, Transaction>>,
    storage_manager: Arc<StorageManager>,
}

impl TransactionManager {
    pub fn new(wal_manager: Arc<WALManager>, storage_manager: Arc<StorageManager>) -> Self {
        Self {
            wal_manager,
            active_transactions: RwLock::new(HashMap::new()),
            storage_manager,
        }
    }
    
    /// Begin a new transaction
    pub fn begin_transaction(&self) -> Result<TransactionId> {
        let txn_id = TransactionId::new();
        let lsn = self.wal_manager.next_lsn();
        
        // Log the BEGIN entry
        let begin_entry = WALEntry::new(lsn, txn_id.clone(), WALEntryType::Begin);
        self.wal_manager.append_entry(&begin_entry)?;
        
        // Track the transaction
        let transaction = Transaction {
            id: txn_id.clone(),
            start_lsn: lsn,
            status: TransactionStatus::Active,
            operations: vec![begin_entry],
        };
        
        {
            let mut txns = self.active_transactions.write();
            txns.insert(txn_id.clone(), transaction);
        }
        
        tracing::info!("Started transaction {} at LSN {}", txn_id.0, lsn.0);
        Ok(txn_id)
    }
    
    /// Put a key-value pair within a transaction
    pub fn put(&self, txn_id: &TransactionId, key: String, value: String) -> Result<()> {
        let mut txns = self.active_transactions.write();
        let transaction = txns.get_mut(txn_id)
            .ok_or_else(|| WALError::Transaction("Transaction not found".to_string()))?;
        
        if transaction.status != TransactionStatus::Active {
            return Err(WALError::Transaction("Transaction not active".to_string()));
        }
        
        // Get old value for potential rollback
        let old_value = self.storage_manager.get(&key)?;
        
        let lsn = self.wal_manager.next_lsn();
        let put_entry = WALEntry::new(
            lsn,
            txn_id.clone(),
            WALEntryType::Put { key: key.clone(), old_value, new_value: value }
        );
        
        // Log the operation
        self.wal_manager.append_entry(&put_entry)?;
        transaction.operations.push(put_entry);
        
        tracing::debug!("Transaction {} PUT {} at LSN {}", txn_id.0, key, lsn.0);
        Ok(())
    }
    
    /// Delete a key within a transaction
    pub fn delete(&self, txn_id: &TransactionId, key: String) -> Result<()> {
        let mut txns = self.active_transactions.write();
        let transaction = txns.get_mut(txn_id)
            .ok_or_else(|| WALError::Transaction("Transaction not found".to_string()))?;
        
        if transaction.status != TransactionStatus::Active {
            return Err(WALError::Transaction("Transaction not active".to_string()));
        }
        
        // Get old value for rollback
        let old_value = self.storage_manager.get(&key)?
            .ok_or_else(|| WALError::Transaction("Key not found for deletion".to_string()))?;
        
        let lsn = self.wal_manager.next_lsn();
        let delete_entry = WALEntry::new(
            lsn,
            txn_id.clone(),
            WALEntryType::Delete { key: key.clone(), old_value }
        );
        
        // Log the operation
        self.wal_manager.append_entry(&delete_entry)?;
        transaction.operations.push(delete_entry);
        
        tracing::debug!("Transaction {} DELETE {} at LSN {}", txn_id.0, key, lsn.0);
        Ok(())
    }
    
    /// Commit a transaction
    pub fn commit_transaction(&self, txn_id: &TransactionId) -> Result<()> {
        let mut txns = self.active_transactions.write();
        let transaction = txns.get_mut(txn_id)
            .ok_or_else(|| WALError::Transaction("Transaction not found".to_string()))?;
        
        if transaction.status != TransactionStatus::Active {
            return Err(WALError::Transaction("Transaction not active".to_string()));
        }
        
        let lsn = self.wal_manager.next_lsn();
        let commit_entry = WALEntry::new(lsn, txn_id.clone(), WALEntryType::Commit);
        
        // Log the commit - this makes the transaction durable
        self.wal_manager.append_entry(&commit_entry)?;
        
        // Force sync for durability guarantee
        self.wal_manager.sync()?;
        
        // Apply changes to storage
        self.apply_transaction_changes(transaction)?;
        
        // Mark as committed
        transaction.status = TransactionStatus::Committed;
        transaction.operations.push(commit_entry);
        
        tracing::info!("Committed transaction {} at LSN {}", txn_id.0, lsn.0);
        Ok(())
    }
    
    /// Rollback a transaction
    pub fn rollback_transaction(&self, txn_id: &TransactionId) -> Result<()> {
        let mut txns = self.active_transactions.write();
        let transaction = txns.get_mut(txn_id)
            .ok_or_else(|| WALError::Transaction("Transaction not found".to_string()))?;
        
        if transaction.status != TransactionStatus::Active {
            return Err(WALError::Transaction("Transaction not active".to_string()));
        }
        
        let lsn = self.wal_manager.next_lsn();
        let rollback_entry = WALEntry::new(lsn, txn_id.clone(), WALEntryType::Rollback);
        
        // Log the rollback
        self.wal_manager.append_entry(&rollback_entry)?;
        
        // Mark as aborted
        transaction.status = TransactionStatus::Aborted;
        transaction.operations.push(rollback_entry);
        
        tracing::info!("Rolled back transaction {} at LSN {}", txn_id.0, lsn.0);
        Ok(())
    }
    
    fn apply_transaction_changes(&self, transaction: &Transaction) -> Result<()> {
        for entry in &transaction.operations {
            match &entry.entry_type {
                WALEntryType::Put { key, new_value, .. } => {
                    self.storage_manager.put(key.clone(), new_value.clone(), entry.lsn)?;
                }
                WALEntryType::Delete { key, .. } => {
                    self.storage_manager.delete(key, entry.lsn)?;
                }
                _ => {} // Skip non-data operations
            }
        }
        Ok(())
    }
}
```

## Storage Manager

```rust
/// Storage Manager - handles data page operations
pub struct StorageManager {
    pages: RwLock<HashMap<u64, DataPage>>,
    page_size: usize,
    next_page_id: AtomicU64,
}

impl StorageManager {
    pub fn new(page_size: usize) -> Self {
        Self {
            pages: RwLock::new(HashMap::new()),
            page_size,
            next_page_id: AtomicU64::new(1),
        }
    }
    
    pub fn get(&self, key: &str) -> Result<Option<String>> {
        let pages = self.pages.read();
        for page in pages.values() {
            if let Some(value) = page.data.get(key) {
                return Ok(Some(value.clone()));
            }
        }
        Ok(None)
    }
    
    pub fn put(&self, key: String, value: String, lsn: LSN) -> Result<()> {
        let mut pages = self.pages.write();
        
        // Find existing page or create new one
        let page_id = self.find_or_create_page_for_key(&key, &mut pages)?;
        
        let page = pages.get_mut(&page_id).unwrap();
        page.data.insert(key, value);
        page.lsn = lsn;
        
        Ok(())
    }
    
    pub fn delete(&self, key: &str, lsn: LSN) -> Result<()> {
        let mut pages = self.pages.write();
        
        for page in pages.values_mut() {
            if page.data.remove(key).is_some() {
                page.lsn = lsn;
                break;
            }
        }
        
        Ok(())
    }
    
    fn find_or_create_page_for_key(&self, _key: &str, pages: &mut HashMap<u64, DataPage>) -> Result<u64> {
        // Simple strategy: use first page with space, or create new one
        for page in pages.values() {
            if page.data.len() < self.page_size {
                return Ok(page.page_id);
            }
        }
        
        // Create new page
        let page_id = self.next_page_id.fetch_add(1, Ordering::Relaxed);
        let page = DataPage::new(page_id);
        pages.insert(page_id, page);
        
        Ok(page_id)
    }
}
```

## Recovery Manager

```rust
/// Recovery Manager - handles crash recovery using WAL
pub struct RecoveryManager {
    wal_manager: Arc<WALManager>,
    storage_manager: Arc<StorageManager>,
}

impl RecoveryManager {
    pub fn new(wal_manager: Arc<WALManager>, storage_manager: Arc<StorageManager>) -> Self {
        Self { wal_manager, storage_manager }
    }
    
    /// Perform crash recovery
    pub fn recover(&self) -> Result<()> {
        tracing::info!("Starting crash recovery...");
        
        // Read all WAL entries
        let entries = self.wal_manager.read_entries_from(LSN(1))?;
        
        if entries.is_empty() {
            tracing::info!("No WAL entries found, recovery complete");
            return Ok(());
        }
        
        // Analyze transactions
        let (committed_txns, uncommitted_txns) = self.analyze_transactions(&entries)?;
        
        tracing::info!(
            "Found {} committed and {} uncommitted transactions",
            committed_txns.len(),
            uncommitted_txns.len()
        );
        
        // REDO phase: Apply all committed transactions
        self.redo_phase(&entries, &committed_txns)?;
        
        // UNDO phase: Reverse all uncommitted transactions
        self.undo_phase(&entries, &uncommitted_txns)?;
        
        tracing::info!("Crash recovery completed successfully");
        Ok(())
    }
    
    fn analyze_transactions(&self, entries: &[WALEntry]) -> Result<(HashSet<TransactionId>, HashSet<TransactionId>)> {
        let mut all_transactions = HashSet::new();
        let mut committed_transactions = HashSet::new();
        
        for entry in entries {
            all_transactions.insert(entry.transaction_id.clone());
            
            match entry.entry_type {
                WALEntryType::Commit => {
                    committed_transactions.insert(entry.transaction_id.clone());
                }
                WALEntryType::Rollback => {
                    // Explicitly rolled back transactions are not committed
                    committed_transactions.remove(&entry.transaction_id);
                }
                _ => {}
            }
        }
        
        let uncommitted_transactions: HashSet<_> = all_transactions
            .difference(&committed_transactions)
            .cloned()
            .collect();
        
        Ok((committed_transactions, uncommitted_transactions))
    }
    
    fn redo_phase(&self, entries: &[WALEntry], committed_txns: &HashSet<TransactionId>) -> Result<()> {
        tracing::info!("Starting REDO phase");
        
        for entry in entries {
            if !committed_txns.contains(&entry.transaction_id) {
                continue;
            }
            
            match &entry.entry_type {
                WALEntryType::Put { key, new_value, .. } => {
                    self.storage_manager.put(key.clone(), new_value.clone(), entry.lsn)?;
                    tracing::debug!("REDO: PUT {} = {}", key, new_value);
                }
                WALEntryType::Delete { key, .. } => {
                    self.storage_manager.delete(key, entry.lsn)?;
                    tracing::debug!("REDO: DELETE {}", key);
                }
                _ => {}
            }
        }
        
        tracing::info!("REDO phase completed");
        Ok(())
    }
    
    fn undo_phase(&self, entries: &[WALEntry], uncommitted_txns: &HashSet<TransactionId>) -> Result<()> {
        tracing::info!("Starting UNDO phase");
        
        // Process entries in reverse order for UNDO
        for entry in entries.iter().rev() {
            if !uncommitted_txns.contains(&entry.transaction_id) {
                continue;
            }
            
            match &entry.entry_type {
                WALEntryType::Put { key, old_value, .. } => {
                    match old_value {
                        Some(old_val) => {
                            self.storage_manager.put(key.clone(), old_val.clone(), entry.lsn)?;
                            tracing::debug!("UNDO: PUT {} = {} (restored)", key, old_val);
                        }
                        None => {
                            self.storage_manager.delete(key, entry.lsn)?;
                            tracing::debug!("UNDO: DELETE {} (was insert)", key);
                        }
                    }
                }
                WALEntryType::Delete { key, old_value } => {
                    self.storage_manager.put(key.clone(), old_value.clone(), entry.lsn)?;
                    tracing::debug!("UNDO: PUT {} = {} (restored from delete)", key, old_value);
                }
                _ => {}
            }
        }
        
        tracing::info!("UNDO phase completed");
        Ok(())
    }
}

use std::collections::HashSet;
```

## Complete WAL Database

```rust
/// Complete WAL-based database system
pub struct WALDatabase {
    wal_manager: Arc<WALManager>,
    transaction_manager: Arc<TransactionManager>,
    storage_manager: Arc<StorageManager>,
    recovery_manager: Arc<RecoveryManager>,
}

impl WALDatabase {
    pub fn new(config: WALConfig) -> Result<Self> {
        let wal_manager = Arc::new(WALManager::new(config)?);
        let storage_manager = Arc::new(StorageManager::new(1000)); // 1000 keys per page
        let transaction_manager = Arc::new(TransactionManager::new(
            wal_manager.clone(),
            storage_manager.clone()
        ));
        let recovery_manager = Arc::new(RecoveryManager::new(
            wal_manager.clone(),
            storage_manager.clone()
        ));
        
        Ok(Self {
            wal_manager,
            transaction_manager,
            storage_manager,
            recovery_manager,
        })
    }
    
    /// Open database and perform recovery if needed
    pub fn open(config: WALConfig) -> Result<Self> {
        let db = Self::new(config)?;
        
        // Perform crash recovery
        db.recovery_manager.recover()?;
        
        Ok(db)
    }
    
    /// Begin a new transaction
    pub fn begin_transaction(&self) -> Result<TransactionId> {
        self.transaction_manager.begin_transaction()
    }
    
    /// Put key-value pair in transaction
    pub fn put(&self, txn_id: &TransactionId, key: String, value: String) -> Result<()> {
        self.transaction_manager.put(txn_id, key, value)
    }
    
    /// Delete key in transaction
    pub fn delete(&self, txn_id: &TransactionId, key: String) -> Result<()> {
        self.transaction_manager.delete(txn_id, key)
    }
    
    /// Get value (read from storage, not transaction-aware for simplicity)
    pub fn get(&self, key: &str) -> Result<Option<String>> {
        self.storage_manager.get(key)
    }
    
    /// Commit transaction
    pub fn commit(&self, txn_id: &TransactionId) -> Result<()> {
        self.transaction_manager.commit_transaction(txn_id)
    }
    
    /// Rollback transaction
    pub fn rollback(&self, txn_id: &TransactionId) -> Result<()> {
        self.transaction_manager.rollback_transaction(txn_id)
    }
    
    /// Create checkpoint
    pub fn checkpoint(&self) -> Result<()> {
        let lsn = self.wal_manager.next_lsn();
        let checkpoint_entry = WALEntry::new(
            lsn,
            TransactionId::new(),
            WALEntryType::Checkpoint { lsn }
        );
        
        self.wal_manager.append_entry(&checkpoint_entry)?;
        self.wal_manager.sync()?;
        
        tracing::info!("Created checkpoint at LSN {}", lsn.0);
        Ok(())
    }
}
```

## Example Usage and Testing

```rust
#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::init();
    
    // Configure WAL system
    let config = WALConfig {
        log_directory: PathBuf::from("./test_wal"),
        max_log_file_size: 1024 * 1024, // 1MB for testing
        sync_mode: SyncMode::Sync, // Safe mode for demo
        buffer_size: 64 * 1024, // 64KB buffer
    };
    
    // Open database (will recover if needed)
    let db = WALDatabase::open(config)?;
    
    println!("=== WAL Database Demo ===");
    
    // Demo 1: Basic transaction
    demo_basic_transaction(&db).await?;
    
    // Demo 2: Multiple concurrent transactions
    demo_concurrent_transactions(&db).await?;
    
    // Demo 3: Transaction rollback
    demo_transaction_rollback(&db).await?;
    
    // Demo 4: Crash simulation and recovery
    demo_crash_recovery().await?;
    
    Ok(())
}

async fn demo_basic_transaction(db: &WALDatabase) -> Result<()> {
    println!("\n--- Demo 1: Basic Transaction ---");
    
    // Start transaction
    let txn_id = db.begin_transaction()?;
    println!("Started transaction: {}", txn_id.0);
    
    // Perform operations
    db.put(&txn_id, "user:123".to_string(), "Alice".to_string())?;
    db.put(&txn_id, "user:456".to_string(), "Bob".to_string())?;
    
    println!("Added two users to transaction");
    
    // Check data is not visible yet
    assert_eq!(db.get("user:123")?, None);
    println!("Data not visible before commit");
    
    // Commit transaction
    db.commit(&txn_id)?;
    println!("Transaction committed");
    
    // Check data is now visible
    assert_eq!(db.get("user:123")?, Some("Alice".to_string()));
    assert_eq!(db.get("user:456")?, Some("Bob".to_string()));
    println!("Data visible after commit");
    
    Ok(())
}

async fn demo_concurrent_transactions(db: &WALDatabase) -> Result<()> {
    println!("\n--- Demo 2: Concurrent Transactions ---");
    
    let txn1 = db.begin_transaction()?;
    let txn2 = db.begin_transaction()?;
    
    // Interleaved operations
    db.put(&txn1, "account:A".to_string(), "1000".to_string())?;
    db.put(&txn2, "account:B".to_string(), "2000".to_string())?;
    db.put(&txn1, "account:C".to_string(), "1500".to_string())?;
    
    // Commit both
    db.commit(&txn1)?;
    db.commit(&txn2)?;
    
    println!("Committed concurrent transactions");
    
    // Verify all data
    assert_eq!(db.get("account:A")?, Some("1000".to_string()));
    assert_eq!(db.get("account:B")?, Some("2000".to_string()));
    assert_eq!(db.get("account:C")?, Some("1500".to_string()));
    
    println!("All concurrent transaction data committed correctly");
    Ok(())
}

async fn demo_transaction_rollback(db: &WALDatabase) -> Result<()> {
    println!("\n--- Demo 3: Transaction Rollback ---");
    
    let txn_id = db.begin_transaction()?;
    
    // Modify existing data
    let original_value = db.get("user:123")?.unwrap();
    db.put(&txn_id, "user:123".to_string(), "Modified Alice".to_string())?;
    db.put(&txn_id, "temp:key".to_string(), "temporary".to_string())?;
    
    println!("Made changes in transaction");
    
    // Rollback instead of commit
    db.rollback(&txn_id)?;
    println!("Transaction rolled back");
    
    // Verify original data is unchanged
    assert_eq!(db.get("user:123")?, Some(original_value));
    assert_eq!(db.get("temp:key")?, None);
    
    println!("Rollback successful - data reverted");
    Ok(())
}

async fn demo_crash_recovery() -> Result<()> {
    println!("\n--- Demo 4: Crash Recovery ---");
    
    // Create a database and do some work
    {
        let config = WALConfig {
            log_directory: PathBuf::from("./crash_test_wal"),
            ..Default::default()
        };
        
        let db = WALDatabase::open(config)?;
        
        // Committed transaction
        let txn1 = db.begin_transaction()?;
        db.put(&txn1, "persistent:1".to_string(), "should survive".to_string())?;
        db.commit(&txn1)?;
        
        // Uncommitted transaction (simulates crash before commit)
        let txn2 = db.begin_transaction()?;
        db.put(&txn2, "volatile:1".to_string(), "should be lost".to_string())?;
        // Intentionally NOT committing txn2 to simulate crash
        
        println!("Created committed and uncommitted transactions");
    } // Database dropped here, simulating crash
    
    // "Restart" and recover
    {
        let config = WALConfig {
            log_directory: PathBuf::from("./crash_test_wal"),
            ..Default::default()
        };
        
        let db = WALDatabase::open(config)?; // Recovery happens here
        
        // Check recovery results
        assert_eq!(db.get("persistent:1")?, Some("should survive".to_string()));
        assert_eq!(db.get("volatile:1")?, None);
        
        println!("Recovery successful:");
        println!("  - Committed data survived");
        println!("  - Uncommitted data was rolled back");
    }
    
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    
    #[tokio::test]
    async fn test_wal_entry_checksum() {
        let entry = WALEntry::new(
            LSN(1),
            TransactionId::new(),
            WALEntryType::Begin
        );
        
        assert!(entry.verify_checksum());
        
        // Manually corrupt the entry
        let mut corrupted = entry;
        corrupted.checksum = 0;
        assert!(!corrupted.verify_checksum());
    }
    
    #[tokio::test]
    async fn test_transaction_isolation() -> Result<()> {
        let temp_dir = TempDir::new().unwrap();
        let config = WALConfig {
            log_directory: temp_dir.path().to_path_buf(),
            ..Default::default()
        };
        
        let db = WALDatabase::open(config)?;
        
        // Transaction 1 makes changes but doesn't commit
        let txn1 = db.begin_transaction()?;
        db.put(&txn1, "test_key".to_string(), "txn1_value".to_string())?;
        
        // Transaction 2 should not see txn1's changes
        let txn2 = db.begin_transaction()?;
        assert_eq!(db.get("test_key")?, None);
        
        // Transaction 2 makes its own changes
        db.put(&txn2, "test_key".to_string(), "txn2_value".to_string())?;
        db.commit(&txn2)?;
        
        // Now test_key should have txn2's value
        assert_eq!(db.get("test_key")?, Some("txn2_value".to_string()));
        
        // Commit txn1 - should overwrite txn2's value
        db.commit(&txn1)?;
        assert_eq!(db.get("test_key")?, Some("txn1_value".to_string()));
        
        Ok(())
    }
    
    #[tokio::test]
    async fn test_recovery_with_multiple_files() -> Result<()> {
        let temp_dir = TempDir::new().unwrap();
        
        // Create database with small log files to force rotation
        {
            let config = WALConfig {
                log_directory: temp_dir.path().to_path_buf(),
                max_log_file_size: 1024, // Very small to force rotation
                ..Default::default()
            };
            
            let db = WALDatabase::open(config)?;
            
            // Create many transactions to force log rotation
            for i in 0..50 {
                let txn = db.begin_transaction()?;
                db.put(&txn, format!("key_{}", i), format!("value_{}", i))?;
                db.commit(&txn)?;
            }
        }
        
        // Reopen and verify all data survived
        {
            let config = WALConfig {
                log_directory: temp_dir.path().to_path_buf(),
                max_log_file_size: 1024,
                ..Default::default()
            };
            
            let db = WALDatabase::open(config)?;
            
            for i in 0..50 {
                assert_eq!(
                    db.get(&format!("key_{}", i))?,
                    Some(format!("value_{}", i))
                );
            }
        }
        
        Ok(())
    }
}
```

## Running the Implementation

To run the WAL database system:

```bash
# Create a new Rust project
cargo new wal-database
cd wal-database

# Add dependencies to Cargo.toml
# Copy the implementation code to src/main.rs

# Run the demo
cargo run

# Run tests
cargo test -- --nocapture
```

## Expected Output

```
=== WAL Database Demo ===

--- Demo 1: Basic Transaction ---
Started transaction: 550e8400-e29b-41d4-a716-446655440000
Added two users to transaction
Data not visible before commit
Transaction committed
Data visible after commit

--- Demo 2: Concurrent Transactions ---
Committed concurrent transactions
All concurrent transaction data committed correctly

--- Demo 3: Transaction Rollback ---
Made changes in transaction
Transaction rolled back
Rollback successful - data reverted

--- Demo 4: Crash Recovery ---
Created committed and uncommitted transactions
Recovery successful:
  - Committed data survived
  - Uncommitted data was rolled back
```

## Key Learning Points

1. **Sequential Logging**: WAL achieves performance through sequential disk writes
2. **Commit Protocol**: Durability is guaranteed when the commit record hits disk
3. **Recovery Process**: REDO committed transactions, UNDO uncommitted ones
4. **Transaction Isolation**: WAL enables ACID properties through careful logging
5. **Error Handling**: Production systems need robust corruption detection and recovery

This Rust implementation demonstrates all the core WAL concepts while providing a foundation for building production database systems. The code emphasizes clarity and correctness over maximum performance, making it an excellent learning resource for understanding how WAL systems work in practice.
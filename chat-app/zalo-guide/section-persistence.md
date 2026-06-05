# Zalo Data Persistence

## Detailed Logic Description

The bridge uses a sophisticated persistence layer to store sessions, message mappings, and user metadata while minimizing disk I/O and footprint.

### 1. Session & Credentials
- **`credentials.json`**: Stores the `zca-js` session including cookies (tough-cookie format) and device identifiers. This is the primary key to the Zalo Web account.
- **`app-session.json`**: Stores the **PC App session** including the `zpw_enk` AES key and raw cookies for the `wpa.zaloapp.com` domains.
- **Internal Context**: While the bridge persists these files, the `zca-js` library maintains a complex in-memory **`AppContext`**. This includes the `zpwServiceMap` (microservice routing table) and `settings` (socket intervals, chunk sizes), which are rebuilt after every successful session restoration.
- **File Reference**: [Bridge: src/zalo/loginApp.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/zalo/loginApp.ts)

### 2. Message Mapping (V2 Format)
The `msg-map.json` file maps Zalo message IDs to Telegram message IDs. 
- **String Interning**: To save space, it uses a string table (`s`) for repeated conversation IDs, UIDs, and message types, referencing them by index.
- **Gzip Compression**: The file is compressed using Gzip level 9 (it is gzipped even though it lacks the `.gz` extension), reducing size by up to 85%.
- **Eviction**: Limited to the last 10,000 messages using a FIFO strategy to prevent the file from growing indefinitely.
- **File Reference**: [src/store.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/store.ts)

### 3. User & Topic Caching
- **`user-cache.json.gz`**: Persistent cache of Zalo UIDs to display names. It includes a normalization layer (`_normName`) for diacritic-insensitive search.
- **`topics.json`**: Maps Zalo thread IDs to Telegram forum topic IDs. This is critical for routing messages to the correct sub-conversation.
- **TTL Caches**: Friends and group lists are kept in memory with a 5-minute TTL to reduce API pressure.

## File References

- **[src/store.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/store.ts)**: Implementation of `msgStore` (L302), `userCache` (L464), and `topics` management (`store` at L61).
- **[src/config.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/config.ts)**: Configuration of the `data/` directory and file paths.

## Code Snippet: V2 Storage Format
```jsonc
{
  "v": 2,
  "s": ["webchat", "uid123", "groupId456"], // String table (Interning)
  "p": [["zaloMsgId1", 101], ["zaloMsgId2", 102]], // Pairs [zaloMsgId, tgMsgId]
  "q": [[101, "zaloId1", "cliId1", 1, "1717500000", 0, ...]] // Quote data
}
```

## Technical Analysis
The transition to a binary-compressed, interned storage format for message mappings solved a critical performance bottleneck where reading/writing large JSON files on every message would cause lag. By filtering out "0" / sentinel IDs, the bridge also avoids common key collision bugs found in earlier versions of the protocol.

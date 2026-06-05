# Zalo-Telegram Poll Synchronization

This section describes how the bridge synchronizes polls between Zalo and Telegram, handling voting, result updates, and poll closures.

## Detailed Logic Description

Poll synchronization is one of the most complex integration points because the Telegram Bot API only sends vote updates (`poll_answer`) for polls **created by the bot itself**.

### 1. The "Bot-Owned Clone" Strategy
When a user sends a native Telegram poll:
1.  **Detection**: The bridge intercepts the `poll` message.
2.  **Zalo Sync**: It creates a corresponding **non-anonymous** poll on Zalo using `api.createPoll`.
3.  **Bot Clone**: The bridge immediately sends a **new** Telegram poll (the "Bot Clone") that identical options.
4.  **Registration**: It stores the mapping (Zalo Poll ID ↔ Bot Poll UUID ↔ Message ID) in `data/polls.json.gz`.
5.  **Clean-up**: The original user-sent poll is ignored by the bridge's routing logic.

### 2. Voting and Score Updating
- **Telegram -> Zalo**: When a user votes on the "Bot Clone," the `poll_answer` event triggers `api.votePoll` on Zalo.
- **Zalo -> Telegram**: When Zalo emits a `UPDATE_BOARD` or poll update event, the bridge fetches the full results and updates a dedicated **Score Message** in the Telegram topic. This message shows live progress using progress-bar emojis.

### 3. Poll Persistence
The bridge uses a persistent Gzipped store (`pollStore`) to ensure that votes can be synced even after a restart.
- **Structure**: Maps the Telegram `poll_id` (a UUID) to the Zalo `pollId`.
- **File Reference**: [Bridge: src/store.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/store.ts#L446)

## Protocol Specification

### 1. Telegram `Poll` Object
Returned when a poll is sent:
```json
{
  "id": "512345678901234567", // UUID string
  "question": "What is your favorite color?",
  "options": [
    { "text": "Blue", "voter_count": 0 },
    { "text": "Red", "voter_count": 0 }
  ],
  "is_closed": false,
  "is_anonymous": false,
  "type": "regular"
}
```

### 2. Telegram `poll_answer` Update
Received when a user votes:
```json
{
  "poll_id": "512345678901234567",
  "user": { "id": 12345, "username": "someone" },
  "option_ids": [0]
}
```

## File References

### Bridge
- **[src/telegram/handler.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/telegram/handler.ts)**: Poll creation and vote forwarding (L2690).
- **[src/zalo/handler.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/zalo/handler.ts)**: Handling Zalo poll updates and "Score Message" generation (L1200).
- **[src/store.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/store.ts)**: Gzipped persistence for poll mappings (L446).

### Telegraf
- **[telegraf-src/src/telegram.ts](https://github.com/telegraf/telegraf/blob/0638cf4cc7ba8467ccb9222726024c99c54d119f/src/telegram.ts)**: Implementation of `sendPoll` (L1000) and `stopPoll` (L1030).

## Technical Analysis
The "Bot-Owned Clone" strategy is a clever workaround for a fundamental limitation of the Telegram Bot API. By forcing polls to be non-anonymous, the bridge can precisely attribute votes to specific users, which is necessary for the Zalo API's `votePoll` method. The use of Gzip for `polls.json.gz` is also significant, as poll metadata can grow rapidly in active groups.

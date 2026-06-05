# Telegram Technical Research Guide

This guide provides an exhaustive technical specification of how the **Zalo-Telegram Bridge** interacts with the official Telegram Bot API and the `telegraf` library. It explores the protocol **"from scratch,"** mapping raw update structures, media forwarding pipelines, and interactive UI components.

**Primary Research Commits**:
- **Bridge (zalo-tg)**: `805709dc70217fd46a1edb79d89ebc5f33874688`
- **Library (telegraf)**: `0638cf4cc7ba8467ccb9222726024c99c54d119f`

---

## Executive Summary

The Telegram integration acts as the primary user interface for the Zalo bridge. It leverages the **Telegram Forum Topics** (Message Threads) feature to organize conversations and uses a **concurrent rate-limit queue** to ensure reliable message delivery.

### Architectural Highlights
- **Topic-Based Routing**: Achieves 1:1 mapping between Zalo chats and Telegram topics using a persistent mapping store.
- **Bot-Owned Clones**: Workaround for Telegram poll limitations, allowing the bridge to receive vote updates.
- **Media Transcoding**: Integrated `ffmpeg` pipeline for converting Telegram-native formats (OGG, WebM) to Zalo-compatible formats (M4A, GIF).
- **IPv4-Forced Transport**: Custom HTTP agents to bypass IPv6 configuration issues in Docker/Linux environments.

---

## Deep-Dive Sections

### 1. [Bot API Interaction Layer](./section-bot-api.md)
*   **ApiClient Internals**: How `telegraf` manages HTTP sessions and payload formatting (JSON vs Multipart).
*   **Local Server Optimization**: Technical detail on `file://` protocol handling and 2GB limit bypassing.

### 2. [Forum Topics & Routing Logic](./section-topics-routing.md)
*   **Thread Mapping**: The 1:1 relationship between Zalo `threadId` and Telegram `message_thread_id`.
*   **Routing Lifecycle**: Sequence diagram of messages traveling from Telegram topics back to Zalo.

### 3. [Queueing & Rate Limiting](./section-queue-rate-limiting.md)
*   **tgQueue Implementation**: Detailed logic of the concurrency-limited (max 5) queue and global pause.
*   **Proxy Pattern**: How the bridge intercepts library-level calls to inject queueing logic transparently.

### 4. [Inbound Update Processing](./section-inbound-processing.md)
*   **Update Lifecycle**: Flowchart of incoming Telegram messages being parsed, filtered, and routed.
*   **Entity Extraction**: Technical spec for parsing mentions and emojis from raw JSON updates.

### 5. [Interactive Commands & UI](./section-commands-ui.md)
*   **Dashboard Architecture**: Construction of "Status" and "Admin" panels using HTML Parse Mode.
*   **Search Workflow**: Dual-path search logic combining Zalo API and local memory caches.

### 6. [Media Handling & Transcoding](./section-media-handling.md)
*   **Album Buffering**: Debounced collection of media group items into single Zalo messages.
*   **Transcoding Pipeline**: Technical detail on `ffmpeg` commands for voice and sticker conversion.

### 7. [Poll Synchronization Strategy](./section-poll-sync.md)
*   **Sync Logic**: The "Bot-Owned Clone" mechanism for receiving vote updates.
*   **Score Dashboards**: Real-time result reflection using persistent poll mappings.

---

## Technical Stack
- **Library**: `telegraf` (Bot API Wrapper).
- **Transcoding**: `ffmpeg` (Spawned via `child_process`).
- **Transport**: `axios` with custom IPv4-forced `https.Agent`.
- **Architecture**: Forum Supergroup / Message Threads.

---
*Created by Gemini CLI - Definitive Telegram Integration Research Session 2026-06-05*

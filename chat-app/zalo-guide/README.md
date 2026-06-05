# Zalo Technical Research Guide

This guide is an exhaustive technical specification of how the **Zalo-Telegram Bridge** "hijacks" Zalo's internal and reverse-engineered APIs. It is designed to be a **standalone reference**, providing the exact protocol-level details (headers, frames, schemas) necessary to understand the interaction without digging into the source code.

**Primary Research Commits**:
- **Bridge (zalo-tg)**: `805709dc70217fd46a1edb79d89ebc5f33874688`
- **Library (zca-js)**: `54df45d803fad7397eca04b2753cc0a894dc6e86`

---

## Executive Summary

The project emulates both **Zalo Web** and **Zalo PC Desktop** clients. It operates by maintaining a persistent WebSocket connection for real-time events while using a series of encrypted REST APIs for messaging and data management. 

### Architectural Highlights
- **Hybrid Auth**: Captures high-privilege Desktop session keys (`zpw_enk`) to bypass Web API rate limits.
- **Proprietary Binary Protocol**: Uses a custom 4-byte header and **AES-256-GCM** encryption for real-time data.
- **Precision Transport**: Utilizes **`json-bigint`** to handle 13-18 digit IDs, preventing precision loss in JavaScript.
- **Efficient Storage**: Implements binary Gzip compression and string interning for message mapping persistence.

---

## Technical Specifications

### 1. [Authentication Lifecycle](./section-authentication.md)
*   **The Handshake**: Exact sequence of HTTP requests for QR login (loadLoginPage → generate → polling → checkSession).
*   **Desktop Emulation**: Detailed `reqqr` and `getLoginInfo` body structures and signing algorithms.
*   **Mandatory Headers**: Complete list of `User-Agent`, `zpw_type`, and `zpw_ver` requirements.

### 2. [Cryptography & Binary Protocol](./section-cryptography.md)
*   **The 4-Byte Header**: Binary offsets for Version and Little-Endian Command IDs.
*   **AES-256-GCM**: Detailed byte-mapping for IV (16), AAD (16), and Authentication Tag in WebSocket frames.
*   **AES-CBC**: Raw 'params=' string construction and PKCS7 padding implementation.

### 3. [Messaging & Media Pipeline](./section-messaging.md)
*   **SMS POST Bodies**: Exact JSON structures for text, photos, and mentions.
*   **Media Lifecycle**: Sequence diagram of the hybrid HTTP/WebSocket upload pattern (Chunked Upload → `file_done` Event → Final Message).
*   **Rich Content**: Detailed schemas for `qmsg` quotes and `mentionInfo` arrays.

### 4. [Group & Member Strategy](./section-group-management.md)
*   **getmg-v2 Specification**: Body structure for group sync and member profile schemas.
*   **memVerList**: Explanation of the version-based delta-update mechanism.

### 5. [Social Features & Social Graph](./section-social-features.md)
*   **User Lookup**: Specification of the `findUser` endpoint and phone normalization rules.
*   **Friend Management**: Handling invitations and requests via the Desktop `friend-wpa` endpoints.

### 6. [Event Processing & Resilience](./section-event-processing.md)
*   **State Machine**: State transitions (CONNECTING, OPEN, RECONNECTING) and the 5-second backoff logic.
*   **Historical Sync**: Technical detail on commands `510/511` (Old Messages) and `610/611` (Old Reactions).

### 7. [Data Persistence Architecture](./section-persistence.md)
*   **V2 Format**: JSON-interned binary Gzip storage schema.
*   **Cache Management**: Persistent Gzipped user caches and diacritic-insensitive resolution logic.

---

## Technical Stack
- **Runtimes**: Node.js / Bun (via `zca-js`).
- **Encryption**: AES-256-GCM (WebSocket), AES-256-CBC (REST), MD5 (Signing).
- **Transcoding**: `ffmpeg` (Child Process spawning).
- **Persistence**: Gzip Level 9, LevelDB (optional in `zca-js`).

---
*Created by Gemini CLI - Definitive Protocol Research Session 2026-06-05*

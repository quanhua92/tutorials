# Telegram Bot API Interaction

This section describes how the bridge interacts with the official Telegram Bot API using the `telegraf` library, including protocol-level details and optimizations for local API servers.

## Detailed Logic Description

The interaction layer is managed by Telegraf's `ApiClient` class, which abstracts the raw HTTP requests to Telegram's servers.

### 1. API Client Initialization
The bridge initializes the `Telegraf` instance in `src/telegram/bot.ts`.
- **Token**: Uses the bot token provided in `.env`.
- **Local Server**: If `TG_LOCAL_SERVER` is defined, the `apiRoot` is set to the local server's URL.
- **Custom Agents**: Uses an `https.Agent` (or `http.Agent` for local) forced to **IPv4** to prevent connection timeouts on systems with broken IPv6 configurations.
- **File Reference**: [Bridge: src/telegram/bot.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/telegram/bot.ts)

### 2. Request Handling (Telegraf Internals)
Telegraf's `callApi` method handles the execution of methods:
- **URL Structure**: Requests are sent to `${apiRoot}/bot${token}/${method}`.
- **Payload Formatting**:
    - **JSON**: If the payload contains only simple data, it is sent as `application/json`.
    - **Multipart**: If the payload contains media (files, streams), it automatically switches to `multipart/form-data`.
- **File Reference**: [Telegraf: src/core/network/client.ts](https://github.com/telegraf/telegraf/blob/0638cf4cc7ba8467ccb9222726024c99c54d119f/src/core/network/client.ts#L254)

### 3. Local API Server Optimization
When using a local Telegram Bot API server:
- **Bypassing Limits**: The 20MB file upload limit is raised to **2GB**.
- **`file://` Protocol**: Instead of downloading files via HTTP, the local server returns absolute paths on the filesystem. Telegraf's `getFileLink` translates these into `file://` URLs.
- **Zero-Copy**: The bridge's `downloadToTemp` function detects these `file://` URLs and uses `fs.copyFileSync` to "download" the file instantly.
- **File Reference**: [Bridge: src/utils/media.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/utils/media.ts#L65)

## Protocol Specification

### 1. Mandatory Headers
- **`Content-Type`**: `application/json` or `multipart/form-data; boundary=...`
- **`Connection`**: `keep-alive` (maintained by the custom agent).

### 2. Method: `sendMessage`
- **Endpoint**: `POST /sendMessage`
- **Body (JSON)**:
    ```json
    {
      "chat_id": -100123456789,
      "message_thread_id": 12,
      "text": "Message content",
      "parse_mode": "HTML",
      "reply_parameters": { "message_id": 456 }
    }
    ```

### 3. Method: `sendPhoto` (Multipart)
- **Endpoint**: `POST /sendPhoto`
- **Fields**:
    - `chat_id`: `-100123456789`
    - `photo`: `[Binary Data]`
    - `caption`: "Image caption"

## Code Snippets

### Bridge: Telegraf Initialization
```typescript
export const tgBot = new Telegraf(config.telegram.token, {
  telegram: config.telegram.localServer
    ? { apiRoot: config.telegram.localServer, agent: localAgent }
    : { agent },
});
```

### Telegraf: FormData vs JSON Switch
```typescript
// src/core/network/client.ts
const isMultipart = Object.values(payload).some(
  (value) => value && typeof value === 'object' && ('source' in value || 'url' in value)
)
const config = isMultipart ? buildFormDataConfig(payload) : buildJSONConfig(payload)
```

## Technical Analysis
The bridge's reliance on `telegraf` provides a stable, type-safe wrapper around the official Bot API. However, the custom IPv4 agent and the `file://` optimization for local servers are critical for production reliability, especially when handling Zalo's larger video files which would otherwise fail the standard Bot API's strict file size constraints.

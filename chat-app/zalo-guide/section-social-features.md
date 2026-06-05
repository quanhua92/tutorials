# Zalo Social Features

## Detailed Logic Description

The bridge implements social features like contact search, friend management, and invitation handling by bridging Telegram commands to Zalo's Web and PC App APIs.

### 1. User Search (`findUser`)
- **Internal Implementation (zca-js)**:
    - **Endpoint**: GET to `https://friend-wpa.zalo.me/api/friend/profile/get`.
    - **Logic**: The library takes the input phone number and automatically handles country code prefixes (e.g., converting '0' to '84' for Vietnam).
    - **Encryption**: Parameters are encrypted using AES-256-CBC and the Base64-encoded `zpw_enk` secret key.
- **Bridge-side Logic**:
    - **Normalization**: Phone numbers are stripped of non-digit characters before being passed to the library.
    - **UI**: Results are shown as interactive Telegram buttons. If a conversation topic already exists for the UID, it is marked with a "✅".
- **File Reference**: [zca-js: src/apis/findUser.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/findUser.ts)

### 2. Friend Request Management
- **Internal Implementation (zca-js)**:
    - **Sending**: POST to `https://friend-wpa.zalo.me/api/friend/sendreq`.
    - **Accepting/Rejecting**: Uses specific command-based API calls under the `/api/friend` namespace.
- **Bridge-side Logic**:
    - **Incoming**: Detected via the `friend_event` listener. The bridge formats the notification and provides "Accept" and "Reject" callback buttons.
    - **Management**: The `/friendrequests` command provides a paginated view of sent and received requests.
    - **Optimization**: The bridge uses the **PC App API** (`friend-wpa.zaloapp.com`) for fetching these lists, as the Web API often truncates results for older requests.
- **File Reference**: [zca-js: src/apis/sendFriendRequest.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/sendFriendRequest.ts)

### 3. Group Invitations (Invite Box)
- **Internal Implementation (zca-js)**:
    - **Listing**: Fetched via `api.getGroupInviteBoxList`.
    - **Joining**: POST to `https://group-wpa.zalo.me/api/group/inv-box/join`.
- **Bridge-side Logic**: Invitations are integrated into the `/friendrequests` UI, allowing users to join groups directly from Telegram.
- **File Reference**: [zca-js: src/apis/joinGroupInviteBox.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/joinGroupInviteBox.ts)

## File References

### Bridge
- **[src/telegram/handler.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/telegram/handler.ts)**: Implementation of `/search` (L699), `/addfriend` (L909), and callback handlers for social actions (L1407, L1497).
- **[src/zalo/appApi.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/zalo/appApi.ts)**: Direct PC App API calls for fetching full friend request lists (L230, L264).

### zca-js
- **[src/apis/findUser.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/findUser.ts)**: Internal logic for user lookup by phone (L4).
- **[src/apis/sendFriendRequest.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/sendFriendRequest.ts)**: Internal logic for sending friend requests (L4).

## Technical Analysis
Zalo's social graph is gated heavily by its proprietary encryption. `zca-js` facilitates access by correctly implementing the `ParamsEncryptor` logic required for these sensitive endpoints. A critical finding is that Zalo requires the **exact** formatting of the phone number (including country code) to return valid search results; `zca-js` handles this normalization internally to ensure the `findUser` call remains robust across different regional phone formats.

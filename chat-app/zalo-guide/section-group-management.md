# Zalo Group & Member Management

## Detailed Logic Description

This project manages Zalo groups and members by combining `zca-js` Web API calls with direct PC App API calls to optimize performance and bypass rate limits.

### 1. API Strategy: Hybrid Approach
- **Web API (zca-js Internals)**: 
    - **Endpoint**: Uses `https://group-wpa.zalo.me/api/group/getmg-v2`.
    - **Logic**: Parameters are JSON-stringified, encrypted using **AES-256-CBC** (zero IV), and sent as a Base64 string in the `params` body field.
- **PC App API (Bridge Custom)**:
    - **Endpoint**: Uses `https://group-wpa.zaloapp.com/api/group/getmg-v2`.
    - **Purpose**: Used as a faster, high-limit alternative for large groups. It hits a different domain than the Web API and is less likely to be throttled.
- **File Reference**: [zca-js: src/apis/getGroupInfo.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/getGroupInfo.ts)

### 2. Member Cache & Resolution
The bridge maintains a multi-layered cache (`userCache`, `friendsCache`, `aliasCache`) to resolve Zalo UIDs to human-readable names.
- **Population**: On startup or when a new group message arrives, `populateGroupMemberCache` synchronizes the member list.
- **Cascading Resolution**:
    1. Check `friendsCache` (contact book).
    2. Check `aliasCache` (manually set Zalo aliases).
    3. Check `userCache` (resolved via previous group fetches; persistent gzipped storage).
    4. Fallback: `api.getUserInfo` (Web API).
- **File Reference**: [Bridge: src/store.ts](https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/src/store.ts)

### 3. Group Operations
- **Joining**: Handled via `api.joinGroupLink` or by approving invitations in the **"Invite Box"** (`api.joinGroupInviteBox`).
- **Leaving**: Handled via `api.leaveGroup`.
- **Admin Flow**: Incoming `group_event` signals (join requests) are forwarded to Telegram as interactive buttons that trigger `api.reviewPendingMemberRequest`.
- **File Reference**: [zca-js: src/apis/joinGroupInviteBox.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/apis/joinGroupInviteBox.ts)

## Group/Social Specification

### 1. `getmg-v2` Request Body
- **Endpoint**: `POST https://group-wpa.zaloapp.com/api/group/getmg-v2`
- **Params (JSON)**:
    ```json
    {
      "gridVerMap": "{\"123456789012345678\": 0}", // Group ID : Version (0 for full sync)
      "type": 30
    }
    ```

### 2. Member Profile Schema
A successful response returns a `gridInfoMap` containing profiles:
```json
{
  "uid": "123456789012345678",
  "dName": "Nguyen Van A",
  "avt": "https://s120-ava.zaloas.com/...",
  "gender": 0,
  "type": 1,         // 1 = Normal user
  "ver": 1717584000  // Version timestamp (used for memVerList)
}
```

### 3. BigInt Handling
Zalo IDs (UIDs and Group IDs) are 13-18 digit integers. 
- **The Issue**: Standard JavaScript `JSON.parse` will round these numbers, causing routing failures.
- **The Fix**: The library uses **`json-bigint`** to ensure these values are treated as strings or specialized BigInt objects during transport.
- **Reference**: [zca-js: src/utils.ts](https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/src/utils.ts#L8)

## Technical Analysis
Zalo's group metadata is fragmented across multiple endpoints. The PC App API's `getmg-v2` is particularly powerful as it returns a **`memVerList`**—a list of version numbers for every member's profile. This allows the bridge to perform "Smart Syncing," only fetching detailed profiles for members whose local cache version is out of date.

Furthermore, because Zalo IDs are 13+ digit integers (exceeding the 53-bit limit of standard JavaScript numbers), the `zca-js` library utilizes **`json-bigint`** for all response parsing. This ensures that UIDs remain precise strings throughout the bridge, preventing the "rounding" errors that often break conversation routing in less sophisticated implementations.

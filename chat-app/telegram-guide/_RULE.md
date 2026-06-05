# Telegram Research Guide Rules

This directory contains a deep-dive analysis of how this project interacts with the official Telegram Bot API, using the `telegraf` library.

## Directory Structure

- `README.md`: The main index and executive summary of the Telegram integration.
- `section-<NAME>.md`: Detailed documentation for a specific functional area.
- `_RULE.md`: This instruction file.

## Requirements for Each Section (.md)

Each section file MUST include:
1.  **Detailed Logic Description**: How the specific feature works at the protocol level. Covers BOTH the bridge logic and the `telegraf` internal implementation.
2.  **File References**: A list of all files involved in this logic.
3.  **GitHub Links**: For every file reference, provide the full URL using the correct repository pattern:
    - **Bridge**: `https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/<FILE_PATH>#L<LINE_NUMBER>`
    - **Telegraf**: `https://github.com/telegraf/telegraf/blob/0638cf4cc7ba8467ccb9222726024c99c54d119f/<FILE_PATH>#L<LINE_NUMBER>`
4.  **Code Snippets**: Critical code snippets from both the bridge and the library.
5.  **Technical Analysis**: Explanation of architectural patterns (e.g., Forum Topics, Queueing).
6.  **Protocol Specification**: Detailed HTTP/REST specifications (JSON bodies, multi-part form-data).

## Reference Data

- **Bridge URL**: `https://github.com/williamcachamwri/zalo-tg` (Commit: `805709dc70217fd46a1edb79d89ebc5f33874688`)
- **Telegraf URL**: `https://github.com/telegraf/telegraf` (Commit: `0638cf4cc7ba8467ccb9222726024c99c54d119f`)
- **Telegraf Source Path**: `./telegraf-src`

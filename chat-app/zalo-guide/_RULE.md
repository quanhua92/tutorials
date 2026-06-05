# Zalo Research Guide Rules

This directory contains a deep-dive analysis of how this project interacts with Zalo's internal APIs, including the core logic of the `zca-js` library.

## Directory Structure

- `README.md`: The main index and executive summary of the Zalo "hijacking" and interaction logic.
- `section-<NAME>.md`: Detailed documentation for a specific functional area of the Zalo integration.
- `_RULE.md`: This instruction file.

## Requirements for Each Section (.md)

Each section file MUST include:
1.  **Detailed Logic Description**: How the specific feature works, including algorithms, sequences, and logic flows. This must cover BOTH the bridge logic and the `zca-js` internal library logic.
2.  **File References**: A list of all files involved in this logic.
3.  **GitHub Links**: For every file reference, provide the full URL using the correct repository pattern:
    - **Bridge**: `https://github.com/williamcachamwri/zalo-tg/blob/805709dc70217fd46a1edb79d89ebc5f33874688/<FILE_PATH>#L<LINE_NUMBER>`
    - **zca-js**: `https://github.com/RFS-ADRENO/zca-js/blob/54df45d803fad7397eca04b2753cc0a894dc6e86/<FILE_PATH>#L<LINE_NUMBER>`
4.  **Code Snippets**: Inclusion of critical code snippets (functions, constants, crypto logic) from both the bridge and the library to illustrate the mechanism.
5.  **Technical Analysis**: Explanation of why certain patterns are used (e.g., how `zca-js` handles the Zalo Web protocol vs. how the bridge handles the PC App API).

## Reference Data

- **Bridge URL**: `https://github.com/williamcachamwri/zalo-tg` (Commit: `805709dc70217fd46a1edb79d89ebc5f33874688`)
- **zca-js URL**: `https://github.com/RFS-ADRENO/zca-js` (Commit: `54df45d803fad7397eca04b2753cc0a894dc6e86`)
- **zca-js Source Path**: `./zca-js-src` (Research this directory for library internals)

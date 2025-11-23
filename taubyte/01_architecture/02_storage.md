# Storage

The storage layer of Tau is a content-addressed storage system, inspired by IPFS. This means that every piece of data stored in the platform is identified by a unique Content Identifier (CID), which is a cryptographic hash of the data.

## Content-Addressing

Content-addressing has several advantages over traditional location-based addressing:

*   **Deduplication:** Since the CID is a hash of the data, identical data will always have the same CID. This means that data can be deduplicated, saving storage space.
*   **Immutability:** Once a piece of data is stored in the platform, it cannot be changed. This is because any change to the data would result in a different CID.
*   **Verification:** The CID can be used to verify the integrity of the data. If the hash of the data does not match the CID, then the data has been corrupted.
*   **Location Independence:** The CID can be used to retrieve the data from any node in the network that has a copy of it. This makes the storage system more resilient and scalable.

## Implementation

Tau uses `ipfs-lite`, a lightweight IPFS peer implementation, to implement its storage layer. `ipfs-lite` provides a full-featured IPFS implementation, including a Bitswap server for exchanging data with other peers, and a Kademlia DHT for discovering peers and content.

The core logic for the IPFS service is located in the `services/substrate/components/ipfs` directory. This service is responsible for creating and managing the `ipfs-lite` peer.

The `pkg/vm-low-orbit/ipfs` directory contains the logic for exposing IPFS functionality to the WebAssembly virtual machine. This allows WebAssembly modules to interact with the storage layer, for example to read and write files.

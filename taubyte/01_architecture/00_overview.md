# Architecture Overview

The Tau architecture is designed to be a decentralized, self-organizing, and resilient platform for running cloud-native applications. It is built on a peer-to-peer network of nodes, each running the `tau` binary. These nodes collaborate to provide a seamless and scalable platform for developers.

The architecture can be broken down into the following key layers:

*   **Networking:** A peer-to-peer overlay network based on `libp2p`. This layer is responsible for node and service discovery, routing, and communication.
*   **Storage:** A content-addressed storage layer, inspired by IPFS. This layer is responsible for storing and retrieving all data in the platform, including code, binaries, and other assets.
*   **Computing:** A WebAssembly-based computing layer. This layer is responsible for executing user code in a sandboxed environment.
*   **Git-Native Management:** A management layer that uses Git as the single source of truth for all configuration. This layer is responsible for managing the state of the platform and ensuring that it is always in sync with the desired configuration.

These layers work together to create a platform that is both powerful and easy to use. The following sections will provide a more detailed explanation of each of these layers.

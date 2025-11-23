# Introduction to Tau

https://github.com/taubyte/tau

Tau is a framework for building low-maintenance, highly scalable cloud computing platforms. It aims to provide an alternative to traditional cloud providers like Vercel, Netlify, and Cloudflare, as well as to complex solutions like Kubernetes.

## Core Principles

The design of Tau is guided by the following principles:

*   **Minimal Configuration:** Tau is designed to be easy to set up and configure. It has built-in auto-discovery capabilities that allow it to gather information about the network and configure itself automatically.
*   **Local Coding Equals Global Production:** Tau simplifies, ports, and sandboxes every aspect of the cloud, making it possible to have a local development environment that is identical to the production environment.
*   **Git-Native:** Tau uses Git as the single source of truth for infrastructure configuration. There are no API calls to create or modify resources; instead, all changes are made through Git commits.
*   **Decentralized:** Tau builds on a peer-to-peer network using libp2p, which enables features like automatic node and service discovery, transport independence, and NAT traversal.
*   **Content-Addressed Storage:** Tau uses content-addressing for storage, similar to IPFS. This provides several benefits, including deduplication, parallel downloads, and content verification.
*   **WebAssembly-Based Computing:** Tau uses WebAssembly as its primary computing engine. This provides a portable and sandboxed environment for running code.

## Getting Started

To get started with Tau, you can follow these steps:

1.  **Install Tau:**
    ```sh
    curl https://get.tau.link/tau | sh
    ```
2.  **Configure:**
    ```sh
    tau config generate -n yourdomain.com -s compute --services all --ip your_public_ip --dv --swarm
    ```
3.  **Launch:**
    ```sh
    tau start -s compute
    ```

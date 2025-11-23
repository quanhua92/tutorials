# Substrate Service

The Substrate service is the core of the computing layer in the Tau platform. It is responsible for running WebAssembly modules in a secure and isolated environment.

## Responsibilities

The Substrate service has the following responsibilities:

*   **WebAssembly VM:** It provides a WebAssembly VM that can be used to run user-provided code.
*   **Module Loading:** It can load WebAssembly modules from different sources, such as the network, the local filesystem, or a URL.
*   **Plugin System:** It has a plugin system that can be used to extend the functionality of the VM.
*   **Component Attachment:** It attaches various components to the VM, such as P2P networking, pub/sub, and storage. These components provide the necessary services for the WebAssembly modules to run.
*   **CPU Monitoring:** It monitors the CPU usage of the node. This information is used for scheduling and load balancing.

## VM Architecture

The VM is built on a layered architecture that makes it very flexible and extensible. The layers are as follows:

*   **Resolver:** The resolver is responsible for resolving module names to their TNS paths.
*   **Backends:** The backends are responsible for fetching the WebAssembly modules from different sources (e.g., DFS, file, URL).
*   **Loader:** The loader is responsible for loading the WebAssembly modules using the provided backends and resolver.
*   **Source:** The source is responsible for providing the WebAssembly modules to the VM.
*   **VM:** The VM is a `wazero`-based WebAssembly runtime.

This layered architecture makes it easy to add new backends or resolvers to support different ways of loading modules.

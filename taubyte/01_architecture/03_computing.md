# Computing

The computing layer of Tau is built on top of WebAssembly (Wasm), a portable and sandboxed binary instruction format. WebAssembly allows Tau to run user-provided code in a secure and isolated environment, without sacrificing performance.

## WebAssembly

WebAssembly has several advantages over other technologies for running user code:

*   **Portability:** WebAssembly is a portable binary format that can run on any platform that has a WebAssembly runtime. This means that you can write your code once and run it anywhere, without having to worry about the underlying operating system or architecture.
*   **Sandboxing:** WebAssembly is sandboxed by default, which means that it cannot access the host system's resources without explicit permission. This makes it a very secure way to run untrusted code.
*   **Performance:** WebAssembly is designed to be fast, and it can run at near-native speed. This makes it a good choice for performance-critical applications.

## WebAssembly System Interface (WASI)

Tau uses the WebAssembly System Interface (WASI) to provide a standard way for WebAssembly modules to interact with the host system. WASI defines a set of APIs for things like file I/O, networking, and environment variables. This allows WebAssembly modules to be more portable and reusable.

## Implementation

Tau uses `wazero`, a zero-dependency WebAssembly runtime for Go, to implement its computing layer. `wazero` is a fast and compliant WebAssembly runtime that supports the `wasi_snapshot_preview1` specification.

The core of the VM implementation is located in the `pkg/vm` package. This package provides a modular and extensible VM architecture that allows you to plug in different VM implementations, loaders, and resolvers.

The `pkg/vm/service/wazero` package provides a `wazero`-based implementation of the VM service. This service is responsible for loading and running WebAssembly modules.

The `pkg/vm-low-orbit` and `pkg/vm-orbit` packages provide a framework for building plugins that can be loaded by the VM. These plugins can be used to extend the functionality of the VM and to provide new features to WebAssembly modules.

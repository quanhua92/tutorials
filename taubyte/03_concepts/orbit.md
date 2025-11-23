# Orbit

Orbit is a plugin system for the Tau VM. It allows you to extend the functionality of the VM and to add new features to your cloud.

## Features

Orbit provides the following features:

*   **Plugin System:** It allows you to create plugins that can be loaded by the VM at runtime.
*   **gRPC Communication:** It uses gRPC for communication between the VM and the plugins. This allows plugins to be written in any language that supports gRPC.
*   **Low-Level API:** It provides a low-level API that allows plugins to interact with the VM and to access its resources.

## Architecture

The Orbit plugin system is built on a client-server architecture. The VM acts as the server, and the plugins act as the clients.

*   **Server:** The VM starts a gRPC server that listens for connections from plugins.
*   **Client:** When a plugin is loaded, it connects to the VM's gRPC server.
*   **Communication:** The VM and the plugin communicate with each other using the gRPC service defined in the `orbit.proto` file.

This architecture allows plugins to be developed and deployed independently of the VM.

## Usage

To create a plugin, you need to do the following:

1.  **Define a gRPC service:** You need to define a gRPC service that will be used for communication between the VM and the plugin.
2.  **Implement the service:** You need to implement the gRPC service in the language of your choice.
3.  **Compile the plugin:** You need to compile the plugin as a shared library (`.so` file).
4.  **Deploy the plugin:** You need to deploy the plugin to the `/tb/plugins/` directory on the nodes where you want to run the plugin.

Once the plugin is deployed, the `substrate` service will automatically load it and make it available to the VM.

For an example of how to create a plugin, see the [ollama-cloud](https://github.com/ollama-cloud) project.

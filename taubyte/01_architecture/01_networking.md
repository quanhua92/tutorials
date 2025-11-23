# Networking

The networking layer of Tau is built on top of `go-libp2p`, a modular and extensible networking stack for peer-to-peer applications. `go-libp2p` allows Tau to create a decentralized and resilient network of nodes that can communicate with each other without relying on a central server.

## Key Features

The networking layer of Tau provides the following key features:

*   **Peer-to-Peer Communication:** Nodes in the Tau network can communicate with each other directly, without going through a central server. This makes the network more resilient and scalable.
*   **Automatic Node and Service Discovery:** Tau uses a Kademlia Distributed Hash Table (DHT) for peer routing and discovery. This allows nodes to find each other and the services they provide automatically.
*   **Transport Independence:** Tau can use any combination of TCP/IP, WebSocket, QUIC, and other transports. This makes it possible for nodes to communicate with each other even if they are behind different types of firewalls or NATs.
*   **NAT Traversal:** Tau uses a combination of techniques, including hole punching and circuit relay, to allow nodes that are not publicly accessible to be part of the cloud.
*   **Private Networks:** Tau supports the creation of private networks using a pre-shared key. This allows you to create a secure and isolated network for your applications.

## Node Types

Tau defines several different types of nodes, each with a different set of capabilities:

*   **Full Node:** A full node is a publicly accessible node that provides a full range of services, including DHT, relay, and NAT services.
*   **Public Node:** A public node is similar to a full node, but with a smaller connection manager.
*   **Lite Public Node:** A lite public node is a public node with an even smaller connection manager.
*   **Simple Node:** A simple node is a node that is not publicly accessible and does not provide any services.
*   **Lite Private Node:** A lite private node is a private node with a smaller connection manager that enables hole punching and NAT port mapping.

This flexibility allows you to configure the networking layer of Tau to meet the specific needs of your application.

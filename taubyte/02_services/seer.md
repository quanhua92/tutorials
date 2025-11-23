# Seer Service

The Seer service is a combined DNS and service discovery service. It is responsible for resolving domain names to IP addresses, and for discovering the nodes that are running a particular service.

## Responsibilities

The Seer service has the following responsibilities:

*   **DNS Server:** It provides a DNS server that can be used to resolve domain names to IP addresses.
*   **Service Discovery:** It provides a service discovery mechanism that can be used to find the nodes that are running a particular service.
*   **Geolocation:** It provides a geolocation service that can be used to find the geographical location of a node.
*   **Health Checks:** It performs health checks on the nodes to ensure that they are alive and responsive.

## DNS Server

The DNS server is the main component of the Seer service. It is responsible for resolving domain names to IP addresses. It has the following features:

*   **Service Domains:** It can resolve service domains (e.g., `auth.taubyte.com`) to the IP addresses of the nodes that are running the requested service.
*   **Registered Domains:** It can resolve registered domains to the IP addresses of the `gateway` or `substrate` nodes.
*   **Caching:** It caches the results of DNS lookups to improve performance.

## Service Discovery

The service discovery mechanism is used to find the nodes that are running a particular service. It works as follows:

1.  **Announcement:** When a service starts, it announces its presence to the Seer service. The announcement contains the name of the service and the IP address of the node that is running the service.
2.  **Query:** When a client wants to connect to a service, it queries the Seer service to get the IP addresses of the nodes that are running the service.
3.  **Response:** The Seer service returns a list of IP addresses of the nodes that are running the service.

This mechanism allows clients to discover services dynamically, without having to hard-code the IP addresses of the nodes.

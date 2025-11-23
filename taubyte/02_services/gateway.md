# Gateway Service

The Gateway service is a reverse proxy that forwards incoming HTTP requests to the appropriate backend service. It is the main entry point for all HTTP traffic into the Tau platform.

## Responsibilities

The Gateway service has the following responsibilities:

*   **HTTP Reverse Proxy:** It acts as a reverse proxy, forwarding incoming HTTP requests to the appropriate backend service.
*   **Service Discovery:** It uses the `substrate` service to discover all the nodes that can handle a given request.
*   **Load Balancing:** It uses metrics to select the best node to handle a given request. This provides a basic form of load balancing.
*   **HTTPS Redirect:** In production mode, it redirects all HTTP requests to HTTPS.

## Request Handling

When the Gateway service receives an HTTP request, it does the following:

1.  It calls the `ProxyHTTP` method on the `substrate` client. This method sends a request to the `substrate` service to find all the nodes that can handle the current request.
2.  The `substrate` service returns a channel of responses. Each response contains metrics about a node that can handle the request.
3.  The Gateway service separates the responses into two lists: website matches and function matches.
4.  It sorts the matches based on their metrics. The `Less` method is used to compare the metrics of two nodes.
5.  It picks the best match (the one with the "less" metrics).
6.  It adds a `ProxyHeader` to the response with the ID of the selected node.
7.  It forwards the request to the selected node using the `tunnel.Frontend` function.

This process ensures that every request is handled by the best available node, providing a high level of performance and reliability.

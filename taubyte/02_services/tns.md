# TNS Service

The TNS (Taubyte Name Service) service is a transactional key-value store that is used to store and retrieve data in the Tau platform. It is a simple and robust service that provides a consistent view of the data to all the nodes in the network.

## Responsibilities

The TNS service has the following responsibilities:

*   **Key-Value Store:** It provides a simple key-value store with a transactional engine.
*   **Data Consistency:** It ensures that the data is always in a consistent state, even in the presence of failures.
*   **P2P Communication:** It uses a p2p stream to handle requests from other nodes.

## Transactional Engine

The transactional engine is the core of the TNS service. It ensures that all write operations are atomic, consistent, isolated, and durable (ACID). The engine works as follows:

1.  **Generate Operations:** When a write request is received, the engine generates a list of operations to be performed. It compares the new data with the existing data and creates `Put` or `Delete` operations as needed.
2.  **Execute Operations:** The engine executes the operations in a transaction. It iterates over the operations and executes them one by one.
3.  **Revert on Failure:** If any operation fails, the engine reverts all the previous operations to ensure that the data is not left in an inconsistent state.

This transactional approach ensures that the data is always in a consistent state, even in the presence of failures.

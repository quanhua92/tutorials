# Hoarder Service

The Hoarder service is responsible for storing and replicating data in the Tau platform. It is a distributed storage service that uses an auction-based mechanism to distribute data among the nodes.

## Responsibilities

The Hoarder service has the following responsibilities:

*   **Data Storage:** It stores data in a key-value database.
*   **Data Replication:** It replicates data to other Hoarder nodes to ensure redundancy and availability.
*   **Data Distribution:** It uses an auction-based mechanism to distribute data among the nodes.

## Auction Process

The auction process works as follows:

1.  **New Auction:** When a new piece of data needs to be stored, a `AuctionNew` message is published on the pub/sub topic. This message contains the CID of the data and other metadata.
2.  **Auction Intent:** Any Hoarder node that receives the `AuctionNew` message can decide to participate in the auction. If it does, it generates a random number and publishes an `AuctionIntent` message with this number.
3.  **Auction End:** After a certain amount of time, an `AuctionEnd` message is published. When a Hoarder node receives this message, it determines the winner of the auction by selecting the participant with the highest random number.
4.  **Store Data:** If the current node is the winner of the auction, it downloads the data from the network and stores it in its local database.

This auction-based mechanism ensures that data is distributed evenly among the Hoarder nodes, and that there are multiple copies of each piece of data to ensure redundancy.

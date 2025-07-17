# Radix Trees: The Compressed Prefix Tree 🛣️


* **`01-concepts-01-the-core-problem.md`**: A standard trie can be very memory-inefficient if many of the keys it stores share long, non-branching prefixes, resulting in long chains of single-child nodes.
* **`01-concepts-02-the-guiding-philosophy.md`**: Compress the paths. A Radix Tree (or PATRICIA trie) is a trie where any node with only one child is merged with its parent. This collapses chains of nodes into single edges labeled with strings instead of characters.
* **`01-concepts-03-key-abstractions.md`**: The `compressed path` and `explicit nodes only at branches`. **Analogy**: An express train route. A normal trie is the local train, stopping at every station. A radix tree is the express train, skipping all the small stations and only stopping at major hubs where lines diverge.
* **`02-guides-01-trie-vs-radix-tree.md`**: A visual guide comparing the trie and radix tree for the words "developer", "development", and "devotion". It clearly shows the node compression in the radix tree.
* **`03-deep-dive-01-ip-routing-tables.md`**: Explores the killer application for radix trees: IP routing. Network routers need to perform fast "longest prefix match" on IP addresses to decide where to send packets. Radix trees provide a memory-efficient and fast way to store these routing tables.

---

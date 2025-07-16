# Consistent Hashing: Stable Distribution in a Changing World 🌍


* **`01-concepts-01-the-core-problem.md`**: When distributing data or requests across a set of servers using a standard `hash(key) % N` formula, adding or removing a server (`N`) forces almost all keys to be remapped, causing a massive data reshuffle.
* **`01-concepts-02-the-guiding-philosophy.md`**: Map both servers and keys to a circle. The core idea is to map keys and servers onto an abstract circle (a hash ring). A key is assigned to the first server encountered by moving clockwise from the key's position. This minimizes remapping when a server is added or removed.
* **`01-concepts-03-key-abstractions.md`**: The `ring`, `nodes` (servers), and `keys`. Analogy: A circular bus route. Stops are servers. People (keys) waiting at any point on the route get on the next bus (server) that arrives.
* **`02-guides-01-simulating-remapping.md`**: A guide comparing the "mod N" approach vs. the consistent hashing approach. Show that when a server is removed, "mod N" causes chaos while consistent hashing only affects a small fraction of keys.
* **`03-deep-dive-01-virtual-nodes.md`**: Explores the problem of uneven distribution on the ring. The solution is **virtual nodes**, where each real server places multiple virtual nodes on the ring to smooth out the distribution. Analogy: A server getting more stops on the bus route to pick up more passengers.

---

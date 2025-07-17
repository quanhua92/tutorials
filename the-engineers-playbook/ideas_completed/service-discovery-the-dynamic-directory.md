# Service Discovery: The Dynamic Directory 📍


* **`01-concepts-01-the-core-problem.md`**: In dynamic environments where services start, stop, and scale, how do services find each other without hardcoding addresses?
* **`01-concepts-02-the-guiding-philosophy.md`**: Maintain a living registry. Services register themselves with a central directory and query it to find others, enabling dynamic routing without configuration changes.
* **`01-concepts-03-key-abstractions.md`**: The `registry`, `health checks`, and `service metadata`. **Analogy**: A dynamic company directory. When employees join, leave, or change departments, the directory automatically updates. To find someone in accounting, you check the current directory, not a printed list.
* **`02-guides-01-consul-basics.md`**: Register a service with Consul, implement health checks, and show how clients discover healthy instances.
* **`03-deep-dive-01-client-vs-server-discovery.md`**: Compares patterns where clients query the registry directly vs. using a load balancer that handles discovery, exploring trade-offs in complexity and performance.

---

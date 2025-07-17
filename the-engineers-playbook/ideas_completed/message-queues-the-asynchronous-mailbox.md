# Message Queues: The Asynchronous Mailbox 📬


* **`01-concepts-01-the-core-problem.md`**: Direct synchronous communication between services creates tight coupling. If a service is down or slow, the entire system grinds to a halt.
* **`01-concepts-02-the-guiding-philosophy.md`**: Decouple producers from consumers. Producers send messages to a queue without knowing or caring who will process them. Consumers pull messages at their own pace.
* **`01-concepts-03-key-abstractions.md`**: The `queue`, `producer`, `consumer`, and `acknowledgment`. **Analogy**: A restaurant's order ticket system. Waiters (producers) put orders on a rail. Cooks (consumers) take and prepare orders at their own speed. The kitchen being busy doesn't block waiters from taking more orders.
* **`02-guides-01-simple-task-queue.md`**: Implement a basic work queue using Redis or RabbitMQ, showing how to distribute tasks among multiple workers.
* **`03-deep-dive-01-delivery-guarantees.md`**: Explores at-most-once, at-least-once, and exactly-once delivery semantics, and the trade-offs between performance and reliability.

---

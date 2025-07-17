# Saga Pattern: The Distributed Transaction Alternative 📖


* **`01-concepts-01-the-core-problem.md`**: Two-phase commit doesn't scale well and can block indefinitely. How can you maintain consistency across multiple services without distributed transactions?
* **`01-concepts-02-the-guiding-philosophy.md`**: Break transactions into steps with compensations. A saga is a sequence of local transactions where each step has a corresponding compensation action that can undo it if later steps fail.
* **`01-concepts-03-key-abstractions.md`**: The `steps`, `compensations`, and `saga coordinator`. **Analogy**: Booking a vacation. You book flight, hotel, and car separately. If the car rental fails, you cancel (compensate) the hotel and flight bookings to maintain consistency.
* **`02-guides-01-order-processing-saga.md`**: Implement an order processing saga that handles payment, inventory, and shipping as separate steps with compensation logic.
* **`03-deep-dive-01-choreography-vs-orchestration.md`**: Compares saga patterns: choreography (events trigger next steps) vs orchestration (central coordinator), examining complexity and failure handling trade-offs.

---

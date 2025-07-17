# Event Sourcing: The Unforgettable History 📖


* **`01-concepts-01-the-core-problem.md`**: Traditional CRUD (Create, Read, Update, Delete) systems only store the current state of data. The history—the "how" and "why" the data reached its current state—is lost forever.
* **`01-concepts-02-the-guiding-philosophy.md`**: Store every change, not the final state. The core philosophy of Event Sourcing is to persist the application's state as a sequence of immutable events. The current state is derived by replaying these events.
* **`01-concepts-03-key-abstractions.md`**: The `Event` (e.g., `OrderPlaced`, `ItemShipped`), the `Event Stream` (a log of events for a specific entity), and `Projections` (read models derived from the event stream). Analogy: A bank account. The current balance (state) is not stored directly; it is calculated from the immutable ledger of all past deposits and withdrawals (events).
* `02-guides-01-modeling-a-shopping-cart.md`: A guide that models a shopping cart using events like `CartCreated`, `ItemAdded`, and `ItemRemoved`. It shows how to calculate the cart's current state by replaying these events.
* **`03-deep-dive-01-event-sourcing-and-cqrs.md`**: Explores the natural synergy between Event Sourcing and CQRS (Command Query Responsibility Segregation). The event stream is the perfect "write model," from which you can build multiple, optimized "read models" (projections) to serve different query needs.

---

# Consensus Algorithms: The Agreement Protocol 🤝


* **`01-concepts-01-the-core-problem.md`**: In a distributed system, how can multiple nodes agree on a single value (like who's the leader) when messages can be delayed, nodes can crash, and there's no global clock?
* **`01-concepts-02-the-guiding-philosophy.md`**: Achieve agreement through rounds of voting. Consensus algorithms ensure that all non-faulty nodes eventually agree on the same value, even in the presence of failures.
* **`01-concepts-03-key-abstractions.md`**: The `proposal`, `voting`, `majority`, and `term/epoch`. **Analogy**: Electing a class president when some students are absent. You need protocols to ensure everyone agrees on the winner, even if some votes are delayed or some students leave mid-election.
* **`02-guides-01-implementing-basic-raft.md`**: Build a simplified version of Raft leader election, showing how nodes campaign, vote, and reach consensus.
* **`03-deep-dive-01-safety-vs-liveness.md`**: The fundamental trade-off in consensus: safety (never disagreeing) vs liveness (eventually making progress), and how different algorithms balance these concerns.

---

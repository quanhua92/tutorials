# Time-Series Databases: The Pulse of Data 📈


* **`01-concepts-01-the-core-problem.md`**: Data that measures something over time (metrics, sensor data, financial prices) has unique characteristics. It's write-heavy, data arrives in chronological order, and queries are almost always over a time range. A general-purpose database is not optimized for this.
* **`01-concepts-02-the-guiding-philosophy.md`**: Treat time as the primary axis. A Time-Series Database (TSDB) is architected from the ground up to optimize for the `(time, value)` nature of its data, using time-based partitioning and specialized compression.
* **`01-concepts-03-key-abstractions.md`**: The `timestamp`, `metric`, `tag` (metadata), and `time-based partitioning`. Analogy: A ship's logbook. Entries are always appended in chronological order. It's easy to look up "What happened between 08:00 and 10:00?". Also, consecutive entries (like "weather: sunny") are often repetitive and can be noted down efficiently.
* **`02-guides-01-modeling-cpu-usage.md`**: A guide on how to structure data for a TSDB. For example, modeling CPU usage as a metric `cpu.load`, with tags like `host=server1`, `region=us-east`.
* **`03-deep-dive-01-time-series-compression.md`**: A deep dive into why TSDBs are so efficient. It covers compression techniques like **delta-of-delta encoding** and **run-length encoding**, which work exceptionally well because consecutive timestamped values often change very little.

---

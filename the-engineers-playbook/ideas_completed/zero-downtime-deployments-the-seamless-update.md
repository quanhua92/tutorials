# Zero-Downtime Deployments: The Seamless Update 🔄


* **`01-concepts-01-the-core-problem.md`**: How do you update a live service without users experiencing errors or downtime? Simply replacing the old version with the new can cause requests to fail during the transition.
* **`01-concepts-02-the-guiding-philosophy.md`**: Maintain multiple versions simultaneously. By running old and new versions side by side and gradually shifting traffic, you can update without any visible disruption.
* **`01-concepts-03-key-abstractions.md`**: The `versions`, `traffic split`, and `rollback capability`. **Analogy**: Replacing a bridge while traffic flows. You build the new bridge alongside, gradually redirect traffic, then remove the old bridge - cars never stop flowing.
* **`02-guides-01-blue-green-deployment.md`**: Implement a blue-green deployment showing how to instantly switch between versions and rollback if needed.
* **`03-deep-dive-01-deployment-strategies-compared.md`**: Compares blue-green, canary, and rolling deployments, analyzing their trade-offs in terms of resource usage, rollback speed, and risk mitigation.

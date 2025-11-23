# Git-Native

Tau is a Git-native platform, which means that Git is the single source of truth for all configuration. There are no API calls to create or modify resources; instead, all changes are made through Git commits.

## GitOps

This approach is often referred to as GitOps. It has several advantages over traditional API-based approaches:

*   **Declarative Configuration:** The entire state of the system is declared in a Git repository. This makes it easy to understand and to reason about the state of the system.
*   **Versioning:** Every change to the system is recorded in the Git history. This makes it easy to track changes and to roll back to a previous state if something goes wrong.
*   **Automation:** The process of applying changes to the system can be automated. This reduces the risk of human error and makes the system more reliable.
*   **Collaboration:** Multiple developers can collaborate on the configuration of the system using the same tools and workflows that they use for their code.

## Implementation

In Tau, every project has a corresponding Git repository. This repository contains all the configuration for the project, including the definitions of the services, functions, websites, and other resources.

When a change is pushed to the Git repository, the `patrick` service is notified. The `patrick` service then creates a job for the `monkey` service to build and deploy the changes.

The `tns` service is used to store the mapping between the Git repository and the project. This allows the other services to find the Git repository for a given project.

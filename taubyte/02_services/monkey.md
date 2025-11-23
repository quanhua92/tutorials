# Monkey Service

The Monkey service is a CI/CD service that is responsible for running jobs that build and compile different types of resources. It is triggered by the `patrick` service, which is responsible for watching Git repositories for changes.

## Responsibilities

The Monkey service has the following responsibilities:

*   **Job Execution:** It runs jobs that build and compile different types of resources, such as websites, libraries, and other code.
*   **Containerized Environment:** It runs jobs in a containerized environment to ensure that they are isolated and have all the necessary dependencies.
*   **Git Integration:** It clones Git repositories and checks out the correct branch before running a job.
*   **Artifact Storage:** It stores the artifacts of a job in the `hoarder` service.

## Job Lifecycle

The lifecycle of a job is as follows:

1.  **Trigger:** A job is triggered by the `patrick` service when a change is pushed to a Git repository.
2.  **Queue:** The job is added to a queue in the `monkey` service.
3.  **Execution:** The `monkey` service picks up the job from the queue and starts executing it.
4.  **Clone:** The `monkey` service clones the Git repository and checks out the correct branch.
5.  **Build:** The `monkey` service builds and compiles the resource using the appropriate builder.
6.  **Store:** The `monkey` service stores the artifacts of the job in the `hoarder` service.
7.  **Cleanup:** The `monkey` service cleans up the environment and deletes the job.

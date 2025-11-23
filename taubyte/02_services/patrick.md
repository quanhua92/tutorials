# Patrick Service

The Patrick service is a webhook handler that is responsible for creating and managing jobs for the `monkey` service. It is the main entry point for all CI/CD jobs in the Tau platform.

## Responsibilities

The Patrick service has the following responsibilities:

*   **Webhook Handling:** It handles webhooks from GitHub and other sources.
*   **Job Creation:** It creates jobs for the `monkey` service based on the information in the webhook payload.
*   **Job Management:** It stores jobs in a key-value database and manages their state.
*   **Job Re-announcement:** It periodically re-announces pending jobs to ensure that they are not lost.

## Job Lifecycle

The lifecycle of a job is as follows:

1.  **Webhook:** The Patrick service receives a webhook from a source such as GitHub.
2.  **Job Creation:** The Patrick service creates a job based on the information in the webhook payload. The job is stored in a key-value database.
3.  **Job Announcement:** The Patrick service announces the job to the `monkey` service by publishing a message on a pub/sub topic.
4.  **Job Locking:** When a `monkey` service picks up a job, it locks the job in the database to prevent other `monkey` services from picking it up.
5.  **Job Execution:** The `monkey` service executes the job.
6.  **Job Unlocking:** When the job is finished, the `monkey` service unlocks the job in the database.

If a job is not picked up by a `monkey` service within a certain amount of time, the Patrick service will re-announce the job to ensure that it is not lost.

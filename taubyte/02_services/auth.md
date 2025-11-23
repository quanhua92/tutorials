# Auth Service

The Auth service is responsible for authentication and authorization in the Tau platform. It acts as an OAuth 2.0 provider, allowing users to log in with their GitHub accounts and authorize applications to access their resources.

## Responsibilities

The Auth service has the following responsibilities:

*   **User Authentication:** It handles the OAuth 2.0 flow with GitHub, allowing users to log in with their GitHub accounts.
*   **Application Authorization:** It allows users to authorize applications to access their resources.
*   **Project and Repository Management:** It manages projects and repositories, including their permissions and access control.
*   **Domain Management:** It manages domains and their TLS certificates.
*   **Key Management:** It manages the public and private keys used for signing and verification.

## Interactions

The Auth service interacts with the following components of the Tau platform:

*   **GitHub:** It uses the GitHub API to authenticate users and to access their repositories.
*   **TNS:** It uses the Taubyte Name Service (TNS) to store and retrieve information about projects, repositories, and domains.
*   **Seer:** It uses the Seer service to announce its presence to the network.
*   **Patrick:** It uses the Patrick service to create and manage webhooks for GitHub repositories.
*   **Database:** It uses a key-value database to store its own data, such as user sessions and access tokens.
*   **HTTP API:** It provides an HTTP API that is used by other services and applications to interact with the Auth service.
*   **P2P Stream:** It uses a p2p stream to communicate with other nodes in the network.

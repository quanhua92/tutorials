# Dream

Dream is a testing and simulation framework for the Tau platform. It allows you to create and manage "universes," which are self-contained Tau environments that can be used to test different scenarios.

## Features

Dream provides the following features:

*   **Universes:** A universe is a collection of services and clients that are running in a simulated environment. You can create universes with different configurations to test different scenarios.
*   **Fixtures:** Dream has a fixture system that allows you to set up and tear down complex test scenarios. For example, you can use fixtures to create projects, inject code, and push code to Git repositories.
*   **Services and Clients:** Dream provides mock implementations of all the Tau services and clients. This allows you to test your code in isolation, without having to run the entire platform.
*   **`dream-cli`:** There is a command-line tool called `dream-cli` that allows you to interact with dream universes from the command line. You can use it to create universes, run fixtures, and inspect the state of the system.

## Usage

Dream is used extensively in the tests for all the other services in the Tau platform. It is a critical part of the development and testing workflow.

Here is an example of how you might use Dream to test a new feature:

1.  Create a new universe with the desired configuration.
2.  Use a fixture to create a new project and inject some code.
3.  Run a test that interacts with the new feature.
4.  Use the `dream-cli` to inspect the state of the system and verify that the feature is working as expected.

Dream is a powerful tool that can be used to test all aspects of the Tau platform. It is an essential tool for any developer who is working on the Tau platform.

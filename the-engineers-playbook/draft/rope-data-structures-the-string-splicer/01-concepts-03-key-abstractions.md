# Key Abstractions: Leaves, Nodes, and Weights

To understand how a Rope works, we need to grasp its three key abstractions: the `leaf`, the `internal node`, and the `weight`.

### 1. The Leaf

A **leaf** is the simplest component of a Rope. It's a node at the bottom of the tree that contains an actual, small, immutable string snippet. These are the fundamental building blocks of our text.

*   **Analogy:** Think of a book. The leaves are the individual, printed pages. Each page contains a chunk of the story.

### 2. The Internal Node

An **internal node** represents the concatenation of its children. It doesn't store any text itself. It simply has two children: a `left` child and a `right` child. The text represented by an internal node is the text of its left child followed by the text of its right child.

*   **Analogy:** The internal nodes are the table of contents or the book's binding. They don't contain the story, but they dictate the order in which the pages (leaves) are read.

### 3. The Weight

The **weight** is a critical piece of information stored in each internal node. It is the total length of all the text in its *left* sub-tree. This is the key to efficient indexing.

### A Detailed View

Let's visualize this with the string "Hello, beautiful world!".

```mermaid
graph TD
    A[Root<br/>weight=17] --> B[Node<br/>weight=7];
    A --> C[Leaf: "world!"];

    B --> D[Leaf: "Hello, "];
    B --> E[Leaf: "beautiful "];

    style C fill:#9cf,stroke:#333,stroke-width:2px
    style D fill:#9cf,stroke:#333,stroke-width:2px
    style E fill:#9cf,stroke:#333,stroke-width:2px
```

*   **Leaves:** We have three leaves: "Hello, " (length 7), "beautiful " (length 10), and "world!" (length 6).
*   **Internal Node `B`:** This node joins "Hello, " and "beautiful ". Its `weight` is 7, the length of its left child (`D`).
*   **Internal Node `A` (Root):** This node joins the result of `B` with "world!". Its `weight` is 17, the length of its entire left sub-tree (`B`), which is 7 + 10.

### How Indexing Works with Weights

Let's find the character at **index 12**.

1.  **Start at the Root (`A`):** The index `12` is less than the root's weight `17`. So, we go **left** to node `B`.
2.  **Move to Node `B`:** The index `12` is *not* less than node `B`'s weight `7`. So, we go **right** to node `E`. Before we do, we must update our index: `12 - 7 = 5`. We are now looking for the character at index `5` within this new subtree.
3.  **Arrive at Leaf `E`:** Node `E` is a leaf containing "beautiful ". We find the character at index `5`, which is **'f'**.

This traversal allows us to find any character in $O(\log n)$ time, where *n* is the number of leaves, which is dramatically faster than scanning a massive string from the beginning.
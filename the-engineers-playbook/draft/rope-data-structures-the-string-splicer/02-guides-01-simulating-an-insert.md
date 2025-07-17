# A Visual Guide: Simulating an Insert

Let's walk through a visual example of how a Rope handles an insertion. We'll start with the string "hello world" and insert "beautiful " in the middle.

### Initial State: "hello world"

First, we represent "hello world" as a Rope. For simplicity, we'll break it into two leaves: "hello " and "world".

```mermaid
graph TD
    A[Root<br/>weight=6] --> B[Leaf: "hello "];
    A --> C[Leaf: "world"];

    style B fill:#9cf,stroke:#333,stroke-width:2px
    style C fill:#9cf,stroke:#333,stroke-width:2px
```

*   The root node has a `weight` of 6, which is the length of its left child, "hello ".

### The Goal: Insert "beautiful " at index 6

We want to insert "beautiful " between "hello " and "world". Here's how the Rope accomplishes this without copying the original strings.

#### Step 1: Split the Rope at Index 6

To insert, we first need to split the tree at the target index. We traverse the tree to find the split point.

1.  Start at the Root (`A`): The index `6` is equal to the root's weight `6`. This is a perfect split point. The left side of the split is the root's left child (`B`), and the right side is the root's right child (`C`).

We now have two independent sub-trees:

```mermaid
graph TD
    subgraph "Left Part"
        B[Leaf: "hello "];
    end
    subgraph "Right Part"
        C[Leaf: "world"];
    end

    style B fill:#9cf,stroke:#333,stroke-width:2px
    style C fill:#9cf,stroke:#333,stroke-width:2px
```

#### Step 2: Create a New Rope for the Inserted Text

We create a new leaf node for the string "beautiful ".

```mermaid
graph TD
    D[Leaf: "beautiful "];
    style D fill:#f9f,stroke:#333,stroke-width:2px
```

#### Step 3: Concatenate the Left Part and the New Text

We create a new internal node to concatenate the "hello " rope (our left part) with the new "beautiful " rope.

```mermaid
graph TD
    E[Node<br/>weight=6] --> B[Leaf: "hello "];
    E --> D[Leaf: "beautiful "];

    style B fill:#9cf,stroke:#333,stroke-width:2px
    style D fill:#f9f,stroke:#333,stroke-width:2px
```

*   This new node `E` has a `weight` of 6 (the length of its new left child, "hello ").

#### Step 4: Concatenate the Result with the Right Part

Finally, we create a new root node to concatenate our newly formed rope (`E`) with the remaining "world" part (`C`).

```mermaid
graph TD
    F[New Root<br/>weight=16] --> E[Node<br/>weight=6];
    F --> C[Leaf: "world"];
    E --> B[Leaf: "hello "];
    E --> D[Leaf: "beautiful "];

    style B fill:#9cf,stroke:#333,stroke-width:2px
    style C fill:#9cf,stroke:#333,stroke-width:2px
    style D fill:#f9f,stroke:#333,stroke-width:2px
```

*   The new root `F` has a `weight` of 16, which is the length of its left subtree (`E`), which is 6 ("hello ") + 10 ("beautiful ").

### Final Result

The final tree represents the string "hello beautiful world". Notice what we *didn't* do. We never modified the original "hello " and "world" leaves. We didn't copy any characters. We only created a few new internal nodes and pointed them to the existing leaves and the new leaf. This is why Ropes are so efficient for this kind of operation. We've performed a major string modification with just a few cheap pointer changes.
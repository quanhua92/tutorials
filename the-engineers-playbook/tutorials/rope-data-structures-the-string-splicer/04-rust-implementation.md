# Practical Implementation: A Simple Rope in Rust

Let's build a basic Rope data structure in Rust to demonstrate the core concepts. This implementation will focus on clarity and will include methods for creation, concatenation, and character indexing.

```rust
use std::sync::Arc;

// The main Rope enum. It can be a Leaf or an Internal Node.
// `Arc` is used to allow shared ownership of the underlying data,
// preventing deep copies and making operations like concatenation cheap.
#[derive(Debug, Clone)]
enum Rope {
    Leaf(Arc<String>),
    Node {
        left: Arc<Rope>,
        right: Arc<Rope>,
        // The `weight` is the length of the left subtree.
        // This is the key to efficient indexing.
        weight: usize,
    },
}

impl Rope {
    // Create a new Rope from a string slice.
    // For simplicity, this always creates a Leaf node.
    pub fn new(text: &str) -> Self {
        Rope::Leaf(Arc::new(text.to_string()))
    }

    // Concatenates two Ropes by creating a new Node.
    // This is an O(1) operation as it only involves creating a new
    // Node and cloning the Arcs, not copying the string data.
    pub fn concat(self, other: Rope) -> Self {
        Rope::Node {
            weight: self.len(),
            left: Arc::new(self),
            right: Arc::new(other),
        }
    }

    // Returns the total length of the text represented by the Rope.
    // This is a recursive operation that traverses the tree.
    pub fn len(&self) -> usize {
        match self {
            Rope::Leaf(s) => s.len(),
            // For a Node, the length is the sum of the lengths of its children.
            // A more optimized version might store the total length in the Node.
            Rope::Node { left, right, .. } => left.len() + right.len(),
        }
    }

    // Retrieves the character at a specific index.
    // This is an O(log n) operation for a balanced tree.
    pub fn char_at(&self, index: usize) -> Option<char> {
        match self {
            Rope::Leaf(s) => s.chars().nth(index),
            Rope::Node { left, right, weight } => {
                if index < *weight {
                    // The character is in the left subtree.
                    left.char_at(index)
                } else {
                    // The character is in the right subtree.
                    // We subtract the weight from the index to get the
                    // relative index in the right subtree.
                    right.char_at(index - *weight)
                }
            }
        }
    }

    // A simple, inefficient split operation for demonstration.
    // A production implementation would be more sophisticated.
    pub fn split(self, index: usize) -> (Rope, Rope) {
        let as_string = self.to_string();
        let (left, right) = as_string.split_at(index);
        (Rope::new(left), Rope::new(right))
    }

    // Converts the Rope to a String.
    // This is an expensive operation and should be used sparingly.
    pub fn to_string(&self) -> String {
        match self {
            Rope::Leaf(s) => s.as_ref().clone(),
            Rope::Node { left, right, .. } => {
                left.to_string() + &right.to_string()
            }
        }
    }
}

fn main() {
    // 1. Create an initial rope.
    let rope = Rope::new("hello world");
    println!("Initial rope: {}", rope.to_string());
    println!("Initial length: {}\n", rope.len());

    // 2. Insert a string in the middle.
    // We do this by splitting the rope and concatenating the pieces.
    let (left, right) = rope.split(6);
    let middle = Rope::new("beautiful ");
    let final_rope = left.concat(middle).concat(right);

    println!("Final rope: {}", final_rope.to_string());
    println!("Final length: {}\n", final_rope.len());

    // 3. Access characters by index to verify.
    println!("Character at index 4: {:?}", final_rope.char_at(4));   // 'o'
    println!("Character at index 6: {:?}", final_rope.char_at(6));   // 'b'
    println!("Character at index 16: {:?}", final_rope.char_at(16)); // 'w'
}
```

### How to Run This Code

1.  Save the code to a file named `main.rs`.
2.  Run `rustc main.rs` to compile it.
3.  Run `./main` to execute it.

### Limitations of this Implementation

This simple example illustrates the power and elegance of the Rope data structure, but it is not production-ready. Here are some key limitations:

*   **No Rebalancing:** The tree is not rebalanced, so repeated, unbalanced operations (like appending one character at a time) will degrade performance to `O(n)`.
*   **Inefficient `split` and `to_string`:** The `split` and `to_string` methods are implemented by converting the entire rope to a flat string, which defeats the purpose of the rope for those operations. A proper implementation would perform these operations directly on the tree structure.
*   **Leaf Node Size:** There is no logic to manage the size of leaf nodes. A real-world rope would split leaves that get too large and join leaves that get too small to maintain efficiency.

Despite these limitations, this code provides a solid foundation for understanding the core principles of a Rope.

### Extended Example: Building a Text Editor Buffer

Let's extend our rope to support more realistic text editor operations:

```rust
impl Rope {
    // Insert text at a specific position
    // This is the most important operation for text editors
    pub fn insert(self, index: usize, text: &str) -> Self {
        let (left, right) = self.split(index);
        let new_text = Rope::new(text);
        left.concat(new_text).concat(right)
    }

    // Delete a range of characters
    pub fn delete(self, start: usize, end: usize) -> Self {
        let (left, _) = self.split(start);
        let (_, right) = self.split(end);
        left.concat(right)
    }

    // Get a substring without converting the entire rope to string
    pub fn substring(&self, start: usize, end: usize) -> String {
        let mut result = String::new();
        self.collect_range(start, end, &mut result);
        result
    }

    // Helper for substring extraction
    fn collect_range(&self, start: usize, end: usize, result: &mut String) {
        if start >= end {
            return;
        }

        match self {
            Rope::Leaf(s) => {
                let s_len = s.len();
                if start < s_len {
                    let actual_end = end.min(s_len);
                    result.push_str(&s[start..actual_end]);
                }
            }
            Rope::Node { left, right, weight } => {
                if start < *weight {
                    // Some of the range is in the left subtree
                    left.collect_range(start, end.min(*weight), result);
                }
                if end > *weight {
                    // Some of the range is in the right subtree
                    right.collect_range(
                        start.saturating_sub(*weight), 
                        end - *weight, 
                        result
                    );
                }
            }
        }
    }
}

// Example usage demonstrating text editor operations
fn text_editor_simulation() {
    println!("=== Text Editor Simulation ===");
    
    // Start with initial content
    let mut document = Rope::new("Hello world!");
    println!("Initial: {}", document.to_string());
    
    // Insert text at the beginning (like typing at cursor position 0)
    document = document.insert(0, "Welcome! ");
    println!("After insert at start: {}", document.to_string());
    
    // Insert text in the middle (like cursor at position 9)
    document = document.insert(9, "beautiful ");
    println!("After insert in middle: {}", document.to_string());
    
    // Delete a range (like selecting and deleting text)
    document = document.delete(9, 18); // Remove "beautiful"
    println!("After deletion: {}", document.to_string());
    
    // Extract a substring (like displaying a portion of text)
    let excerpt = document.substring(0, 8);
    println!("Excerpt (0-8): '{}'", excerpt);
    
    // Show individual character access
    if let Some(ch) = document.char_at(5) {
        println!("Character at position 5: '{}'", ch);
    }
    
    println!("Final document length: {}", document.len());
}
```

### Performance Testing Framework

Here's a simple framework to measure rope performance:

```rust
use std::time::Instant;

fn benchmark_operations() {
    println!("\n=== Performance Benchmarks ===");
    
    // Create a moderately large document
    let large_text = "Lorem ipsum dolor sit amet. ".repeat(1000);
    let rope = Rope::new(&large_text);
    
    // Benchmark character access
    let start = Instant::now();
    for i in 0..1000 {
        rope.char_at(i * 27); // Access every 27th character
    }
    let char_access_time = start.elapsed();
    
    // Benchmark insertion at the beginning
    let start = Instant::now();
    let mut test_rope = rope.clone();
    for i in 0..100 {
        test_rope = test_rope.insert(0, &format!("Insert {} ", i));
    }
    let insert_time = start.elapsed();
    
    // Benchmark concatenation
    let start = Instant::now();
    let rope1 = Rope::new("First half of document");
    let rope2 = Rope::new("Second half of document");
    let mut combined = rope1.clone();
    for _ in 0..1000 {
        combined = combined.concat(rope2.clone());
    }
    let concat_time = start.elapsed();
    
    println!("Character access (1000 operations): {:?}", char_access_time);
    println!("Insertions at start (100 operations): {:?}", insert_time);
    println!("Concatenations (1000 operations): {:?}", concat_time);
}
```

### Complete Example with All Features

```rust
fn comprehensive_example() {
    println!("\n=== Comprehensive Rope Demo ===");
    
    // Simulate editing a configuration file
    let mut config = Rope::new(r#"# Configuration File
server_port = 8080
debug_mode = false
max_connections = 100
"#);
    
    println!("Original config:\n{}", config.to_string());
    
    // Add a new configuration line at the end
    let config_len = config.len();
    config = config.insert(config_len, "log_level = info\n");
    
    // Modify the debug_mode setting (find and replace simulation)
    // In a real implementation, you'd have a find() method
    let debug_line_start = config.to_string().find("debug_mode = false").unwrap();
    config = config.delete(debug_line_start, debug_line_start + 18);
    config = config.insert(debug_line_start, "debug_mode = true");
    
    // Insert a comment at the beginning
    config = config.insert(0, "# Updated configuration\n");
    
    println!("Modified config:\n{}", config.to_string());
    
    // Extract just the port configuration
    let full_text = config.to_string();
    if let Some(port_start) = full_text.find("server_port") {
        let port_end = full_text[port_start..].find('\n').unwrap_or(0) + port_start;
        let port_line = config.substring(port_start, port_end);
        println!("Port configuration: {}", port_line);
    }
}

// Updated main function
fn main() {
    // Original simple example
    let rope = Rope::new("hello world");
    println!("Initial rope: {}", rope.to_string());
    
    let (left, right) = rope.split(6);
    let middle = Rope::new("beautiful ");
    let final_rope = left.concat(middle).concat(right);
    
    println!("Final rope: {}", final_rope.to_string());
    
    // Extended examples
    text_editor_simulation();
    benchmark_operations();
    comprehensive_example();
}
```

### Understanding the Performance Characteristics

The key insight from this implementation is seeing how different operations scale:

```rust
// O(1) - Just creates new internal nodes
let concatenated = rope1.concat(rope2);

// O(log n) - Traverses tree to find split point
let (left, right) = rope.split(index);

// O(log n) - Traverses tree to find character
let character = rope.char_at(index);

// O(n) - Must traverse entire tree (this is where our simple implementation falls short)
let full_string = rope.to_string();
```

This implementation demonstrates the core concepts while highlighting where a production rope would need more sophistication—particularly in efficient substring extraction, tree rebalancing, and optimized string conversion.
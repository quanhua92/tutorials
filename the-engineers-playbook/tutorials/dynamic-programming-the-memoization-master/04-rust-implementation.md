# Dynamic Programming Implementation in Rust

This section provides complete, idiomatic Rust implementations of classic dynamic programming problems. Each implementation demonstrates different DP patterns and Rust-specific optimizations.

## Project Setup

First, let's set up a complete Rust project structure:

```toml
# Cargo.toml
[package]
name = "dynamic-programming-examples"
version = "0.1.0"
edition = "2021"

[dependencies]
```

## Implementation 1: Fibonacci Sequence

Let's implement all variants of the Fibonacci solution:

```rust
use std::collections::HashMap;
use std::time::Instant;

pub struct FibonacciSolver;

impl FibonacciSolver {
    /// Naive recursive implementation - O(2^n) time, O(n) space
    pub fn naive(n: u32) -> u64 {
        if n <= 1 {
            n as u64
        } else {
            Self::naive(n - 1) + Self::naive(n - 2)
        }
    }

    /// Memoized (top-down) implementation - O(n) time, O(n) space
    pub fn memoized(n: u32) -> u64 {
        let mut memo = HashMap::new();
        Self::memoized_helper(n, &mut memo)
    }

    fn memoized_helper(n: u32, memo: &mut HashMap<u32, u64>) -> u64 {
        if let Some(&result) = memo.get(&n) {
            return result;
        }

        let result = if n <= 1 {
            n as u64
        } else {
            Self::memoized_helper(n - 1, memo) + Self::memoized_helper(n - 2, memo)
        };

        memo.insert(n, result);
        result
    }

    /// Tabulation (bottom-up) implementation - O(n) time, O(n) space
    pub fn tabulation(n: u32) -> u64 {
        if n <= 1 {
            return n as u64;
        }

        let mut dp = vec![0; (n + 1) as usize];
        dp[0] = 0;
        dp[1] = 1;

        for i in 2..=n {
            dp[i as usize] = dp[(i - 1) as usize] + dp[(i - 2) as usize];
        }

        dp[n as usize]
    }

    /// Space-optimized implementation - O(n) time, O(1) space
    pub fn optimized(n: u32) -> u64 {
        if n <= 1 {
            return n as u64;
        }

        let mut prev2 = 0;
        let mut prev1 = 1;

        for _ in 2..=n {
            let current = prev1 + prev2;
            prev2 = prev1;
            prev1 = current;
        }

        prev1
    }
}

#[cfg(test)]
mod fibonacci_tests {
    use super::*;

    #[test]
    fn test_fibonacci_correctness() {
        let test_cases = vec![
            (0, 0),
            (1, 1),
            (2, 1),
            (3, 2),
            (4, 3),
            (5, 5),
            (6, 8),
            (10, 55),
        ];

        for (n, expected) in test_cases {
            assert_eq!(FibonacciSolver::memoized(n), expected);
            assert_eq!(FibonacciSolver::tabulation(n), expected);
            assert_eq!(FibonacciSolver::optimized(n), expected);
            
            if n <= 20 {  // Only test naive for small inputs
                assert_eq!(FibonacciSolver::naive(n), expected);
            }
        }
    }

    #[test]
    fn test_fibonacci_large_input() {
        let n = 50;
        let expected = 12586269025;
        
        assert_eq!(FibonacciSolver::memoized(n), expected);
        assert_eq!(FibonacciSolver::tabulation(n), expected);
        assert_eq!(FibonacciSolver::optimized(n), expected);
    }
}
```

## Implementation 2: Coin Change Problem

A classic optimization problem demonstrating multiple DP patterns:

```rust
use std::collections::HashMap;

pub struct CoinChange;

impl CoinChange {
    /// Minimum coins needed to make amount (memoized)
    pub fn min_coins_memo(coins: &[u32], amount: u32) -> Option<u32> {
        let mut memo = HashMap::new();
        let result = Self::min_coins_helper(coins, amount, &mut memo);
        if result == u32::MAX {
            None
        } else {
            Some(result)
        }
    }

    fn min_coins_helper(
        coins: &[u32],
        amount: u32,
        memo: &mut HashMap<u32, u32>,
    ) -> u32 {
        if amount == 0 {
            return 0;
        }

        if let Some(&result) = memo.get(&amount) {
            return result;
        }

        let mut min_coins = u32::MAX;
        for &coin in coins {
            if coin <= amount {
                let sub_result = Self::min_coins_helper(coins, amount - coin, memo);
                if sub_result != u32::MAX {
                    min_coins = min_coins.min(1 + sub_result);
                }
            }
        }

        memo.insert(amount, min_coins);
        min_coins
    }

    /// Minimum coins needed to make amount (tabulation)
    pub fn min_coins_tab(coins: &[u32], amount: u32) -> Option<u32> {
        let mut dp = vec![u32::MAX; (amount + 1) as usize];
        dp[0] = 0;

        for i in 1..=amount {
            for &coin in coins {
                if coin <= i && dp[(i - coin) as usize] != u32::MAX {
                    dp[i as usize] = dp[i as usize].min(1 + dp[(i - coin) as usize]);
                }
            }
        }

        if dp[amount as usize] == u32::MAX {
            None
        } else {
            Some(dp[amount as usize])
        }
    }

    /// Count number of ways to make amount
    pub fn count_ways(coins: &[u32], amount: u32) -> u64 {
        let mut dp = vec![0u64; (amount + 1) as usize];
        dp[0] = 1;

        for &coin in coins {
            for i in coin..=amount {
                dp[i as usize] += dp[(i - coin) as usize];
            }
        }

        dp[amount as usize]
    }

    /// Return the actual coins used (with backtracking)
    pub fn min_coins_with_solution(coins: &[u32], amount: u32) -> Option<Vec<u32>> {
        let mut dp = vec![u32::MAX; (amount + 1) as usize];
        let mut parent = vec![None; (amount + 1) as usize];
        dp[0] = 0;

        for i in 1..=amount {
            for &coin in coins {
                if coin <= i && dp[(i - coin) as usize] != u32::MAX {
                    if dp[i as usize] > 1 + dp[(i - coin) as usize] {
                        dp[i as usize] = 1 + dp[(i - coin) as usize];
                        parent[i as usize] = Some(coin);
                    }
                }
            }
        }

        if dp[amount as usize] == u32::MAX {
            return None;
        }

        // Reconstruct solution
        let mut result = Vec::new();
        let mut current = amount;
        while current > 0 {
            if let Some(coin) = parent[current as usize] {
                result.push(coin);
                current -= coin;
            } else {
                break;
            }
        }

        Some(result)
    }
}

#[cfg(test)]
mod coin_change_tests {
    use super::*;

    #[test]
    fn test_min_coins() {
        let coins = vec![1, 3, 4];
        
        assert_eq!(CoinChange::min_coins_memo(&coins, 6), Some(2)); // 3 + 3
        assert_eq!(CoinChange::min_coins_tab(&coins, 6), Some(2));
        assert_eq!(CoinChange::min_coins_memo(&coins, 0), Some(0));
        assert_eq!(CoinChange::min_coins_memo(&coins, 2), Some(2)); // 1 + 1
    }

    #[test]
    fn test_impossible_amount() {
        let coins = vec![3, 5];
        assert_eq!(CoinChange::min_coins_memo(&coins, 1), None);
        assert_eq!(CoinChange::min_coins_tab(&coins, 1), None);
    }

    #[test]
    fn test_count_ways() {
        let coins = vec![1, 2, 5];
        assert_eq!(CoinChange::count_ways(&coins, 5), 4);
        // Ways: [5], [2,2,1], [2,1,1,1], [1,1,1,1,1]
    }

    #[test]
    fn test_solution_reconstruction() {
        let coins = vec![1, 3, 4];
        let solution = CoinChange::min_coins_with_solution(&coins, 6).unwrap();
        assert_eq!(solution.len(), 2);
        assert_eq!(solution.iter().sum::<u32>(), 6);
    }
}
```

## Implementation 3: Longest Common Subsequence (LCS)

A classic string DP problem with 2D state space:

```rust
pub struct LongestCommonSubsequence;

impl LongestCommonSubsequence {
    /// Find the length of LCS (memoized)
    pub fn lcs_length_memo(s1: &str, s2: &str) -> usize {
        let chars1: Vec<char> = s1.chars().collect();
        let chars2: Vec<char> = s2.chars().collect();
        let mut memo = std::collections::HashMap::new();
        
        Self::lcs_helper(&chars1, &chars2, 0, 0, &mut memo)
    }

    fn lcs_helper(
        s1: &[char],
        s2: &[char],
        i: usize,
        j: usize,
        memo: &mut std::collections::HashMap<(usize, usize), usize>,
    ) -> usize {
        if i >= s1.len() || j >= s2.len() {
            return 0;
        }

        if let Some(&result) = memo.get(&(i, j)) {
            return result;
        }

        let result = if s1[i] == s2[j] {
            1 + Self::lcs_helper(s1, s2, i + 1, j + 1, memo)
        } else {
            std::cmp::max(
                Self::lcs_helper(s1, s2, i + 1, j, memo),
                Self::lcs_helper(s1, s2, i, j + 1, memo),
            )
        };

        memo.insert((i, j), result);
        result
    }

    /// Find the length of LCS (tabulation)
    pub fn lcs_length_tab(s1: &str, s2: &str) -> usize {
        let chars1: Vec<char> = s1.chars().collect();
        let chars2: Vec<char> = s2.chars().collect();
        let m = chars1.len();
        let n = chars2.len();

        let mut dp = vec![vec![0; n + 1]; m + 1];

        for i in 1..=m {
            for j in 1..=n {
                dp[i][j] = if chars1[i - 1] == chars2[j - 1] {
                    1 + dp[i - 1][j - 1]
                } else {
                    std::cmp::max(dp[i - 1][j], dp[i][j - 1])
                };
            }
        }

        dp[m][n]
    }

    /// Find the actual LCS string
    pub fn lcs_string(s1: &str, s2: &str) -> String {
        let chars1: Vec<char> = s1.chars().collect();
        let chars2: Vec<char> = s2.chars().collect();
        let m = chars1.len();
        let n = chars2.len();

        let mut dp = vec![vec![0; n + 1]; m + 1];

        // Fill the DP table
        for i in 1..=m {
            for j in 1..=n {
                dp[i][j] = if chars1[i - 1] == chars2[j - 1] {
                    1 + dp[i - 1][j - 1]
                } else {
                    std::cmp::max(dp[i - 1][j], dp[i][j - 1])
                };
            }
        }

        // Reconstruct the LCS
        let mut result = Vec::new();
        let mut i = m;
        let mut j = n;

        while i > 0 && j > 0 {
            if chars1[i - 1] == chars2[j - 1] {
                result.push(chars1[i - 1]);
                i -= 1;
                j -= 1;
            } else if dp[i - 1][j] > dp[i][j - 1] {
                i -= 1;
            } else {
                j -= 1;
            }
        }

        result.reverse();
        result.into_iter().collect()
    }

    /// Space-optimized version (only length, not the actual LCS)
    pub fn lcs_length_optimized(s1: &str, s2: &str) -> usize {
        let chars1: Vec<char> = s1.chars().collect();
        let chars2: Vec<char> = s2.chars().collect();
        let m = chars1.len();
        let n = chars2.len();

        // Use only two rows instead of full table
        let mut prev = vec![0; n + 1];
        let mut curr = vec![0; n + 1];

        for i in 1..=m {
            for j in 1..=n {
                curr[j] = if chars1[i - 1] == chars2[j - 1] {
                    1 + prev[j - 1]
                } else {
                    std::cmp::max(prev[j], curr[j - 1])
                };
            }
            std::mem::swap(&mut prev, &mut curr);
        }

        prev[n]
    }
}

#[cfg(test)]
mod lcs_tests {
    use super::*;

    #[test]
    fn test_lcs_length() {
        assert_eq!(LongestCommonSubsequence::lcs_length_memo("ABCDGH", "AEDFHR"), 3);
        assert_eq!(LongestCommonSubsequence::lcs_length_tab("ABCDGH", "AEDFHR"), 3);
        assert_eq!(LongestCommonSubsequence::lcs_length_optimized("ABCDGH", "AEDFHR"), 3);
    }

    #[test]
    fn test_lcs_string() {
        assert_eq!(LongestCommonSubsequence::lcs_string("ABCDGH", "AEDFHR"), "ADH");
        assert_eq!(LongestCommonSubsequence::lcs_string("AGGTAB", "GXTXAYB"), "GTAB");
    }

    #[test]
    fn test_empty_strings() {
        assert_eq!(LongestCommonSubsequence::lcs_length_memo("", "ABC"), 0);
        assert_eq!(LongestCommonSubsequence::lcs_length_memo("ABC", ""), 0);
        assert_eq!(LongestCommonSubsequence::lcs_string("", "ABC"), "");
    }
}
```

## Implementation 4: 0/1 Knapsack Problem

A classic optimization problem with resource constraints:

```rust
#[derive(Clone, Debug)]
pub struct Item {
    pub weight: u32,
    pub value: u32,
    pub name: String,
}

pub struct Knapsack;

impl Knapsack {
    /// Maximum value that can be obtained (memoized)
    pub fn max_value_memo(items: &[Item], capacity: u32) -> u32 {
        let mut memo = std::collections::HashMap::new();
        Self::knapsack_helper(items, capacity, 0, &mut memo)
    }

    fn knapsack_helper(
        items: &[Item],
        capacity: u32,
        index: usize,
        memo: &mut std::collections::HashMap<(usize, u32), u32>,
    ) -> u32 {
        if index >= items.len() || capacity == 0 {
            return 0;
        }

        if let Some(&result) = memo.get(&(index, capacity)) {
            return result;
        }

        let result = if items[index].weight <= capacity {
            std::cmp::max(
                // Don't take the item
                Self::knapsack_helper(items, capacity, index + 1, memo),
                // Take the item
                items[index].value + Self::knapsack_helper(
                    items,
                    capacity - items[index].weight,
                    index + 1,
                    memo,
                ),
            )
        } else {
            // Can't take the item
            Self::knapsack_helper(items, capacity, index + 1, memo)
        };

        memo.insert((index, capacity), result);
        result
    }

    /// Maximum value that can be obtained (tabulation)
    pub fn max_value_tab(items: &[Item], capacity: u32) -> u32 {
        let n = items.len();
        let mut dp = vec![vec![0; (capacity + 1) as usize]; n + 1];

        for i in 1..=n {
            for w in 1..=capacity {
                dp[i][w as usize] = if items[i - 1].weight <= w {
                    std::cmp::max(
                        dp[i - 1][w as usize], // Don't take item
                        items[i - 1].value + dp[i - 1][(w - items[i - 1].weight) as usize], // Take item
                    )
                } else {
                    dp[i - 1][w as usize] // Can't take item
                };
            }
        }

        dp[n][capacity as usize]
    }

    /// Find the actual items selected
    pub fn selected_items(items: &[Item], capacity: u32) -> (u32, Vec<Item>) {
        let n = items.len();
        let mut dp = vec![vec![0; (capacity + 1) as usize]; n + 1];

        // Fill the DP table
        for i in 1..=n {
            for w in 1..=capacity {
                dp[i][w as usize] = if items[i - 1].weight <= w {
                    std::cmp::max(
                        dp[i - 1][w as usize],
                        items[i - 1].value + dp[i - 1][(w - items[i - 1].weight) as usize],
                    )
                } else {
                    dp[i - 1][w as usize]
                };
            }
        }

        // Backtrack to find selected items
        let mut selected = Vec::new();
        let mut w = capacity;
        let mut i = n;

        while i > 0 && w > 0 {
            if dp[i][w as usize] != dp[i - 1][w as usize] {
                selected.push(items[i - 1].clone());
                w -= items[i - 1].weight;
            }
            i -= 1;
        }

        (dp[n][capacity as usize], selected)
    }

    /// Space-optimized version
    pub fn max_value_optimized(items: &[Item], capacity: u32) -> u32 {
        let mut dp = vec![0; (capacity + 1) as usize];

        for item in items {
            for w in (item.weight..=capacity).rev() {
                dp[w as usize] = std::cmp::max(
                    dp[w as usize],
                    item.value + dp[(w - item.weight) as usize],
                );
            }
        }

        dp[capacity as usize]
    }
}

#[cfg(test)]
mod knapsack_tests {
    use super::*;

    fn sample_items() -> Vec<Item> {
        vec![
            Item { weight: 10, value: 60, name: "Item1".to_string() },
            Item { weight: 20, value: 100, name: "Item2".to_string() },
            Item { weight: 30, value: 120, name: "Item3".to_string() },
        ]
    }

    #[test]
    fn test_knapsack_max_value() {
        let items = sample_items();
        let capacity = 50;
        
        assert_eq!(Knapsack::max_value_memo(&items, capacity), 220);
        assert_eq!(Knapsack::max_value_tab(&items, capacity), 220);
        assert_eq!(Knapsack::max_value_optimized(&items, capacity), 220);
    }

    #[test]
    fn test_selected_items() {
        let items = sample_items();
        let capacity = 50;
        
        let (max_value, selected) = Knapsack::selected_items(&items, capacity);
        assert_eq!(max_value, 220);
        assert_eq!(selected.len(), 2);
        
        let total_weight: u32 = selected.iter().map(|item| item.weight).sum();
        let total_value: u32 = selected.iter().map(|item| item.value).sum();
        assert!(total_weight <= capacity);
        assert_eq!(total_value, max_value);
    }
}
```

## Benchmark Suite

Here's a comprehensive benchmark to compare different implementations:

```rust
use std::time::Instant;

pub struct DpBenchmark;

impl DpBenchmark {
    pub fn benchmark_fibonacci(n: u32) {
        println!("=== Fibonacci Benchmark (n = {}) ===", n);
        
        if n <= 35 {
            let start = Instant::now();
            let result = FibonacciSolver::naive(n);
            let duration = start.elapsed();
            println!("Naive:       {} in {:?}", result, duration);
        }
        
        let start = Instant::now();
        let result = FibonacciSolver::memoized(n);
        let duration = start.elapsed();
        println!("Memoized:    {} in {:?}", result, duration);
        
        let start = Instant::now();
        let result = FibonacciSolver::tabulation(n);
        let duration = start.elapsed();
        println!("Tabulation:  {} in {:?}", result, duration);
        
        let start = Instant::now();
        let result = FibonacciSolver::optimized(n);
        let duration = start.elapsed();
        println!("Optimized:   {} in {:?}", result, duration);
        
        println!();
    }
    
    pub fn benchmark_coin_change(coins: &[u32], amount: u32) {
        println!("=== Coin Change Benchmark (amount = {}) ===", amount);
        
        let start = Instant::now();
        let result = CoinChange::min_coins_memo(coins, amount);
        let duration = start.elapsed();
        println!("Memoized:    {:?} in {:?}", result, duration);
        
        let start = Instant::now();
        let result = CoinChange::min_coins_tab(coins, amount);
        let duration = start.elapsed();
        println!("Tabulation:  {:?} in {:?}", result, duration);
        
        println!();
    }
    
    pub fn benchmark_lcs(s1: &str, s2: &str) {
        println!("=== LCS Benchmark (lengths {} vs {}) ===", s1.len(), s2.len());
        
        let start = Instant::now();
        let result = LongestCommonSubsequence::lcs_length_memo(s1, s2);
        let duration = start.elapsed();
        println!("Memoized:    {} in {:?}", result, duration);
        
        let start = Instant::now();
        let result = LongestCommonSubsequence::lcs_length_tab(s1, s2);
        let duration = start.elapsed();
        println!("Tabulation:  {} in {:?}", result, duration);
        
        let start = Instant::now();
        let result = LongestCommonSubsequence::lcs_length_optimized(s1, s2);
        let duration = start.elapsed();
        println!("Optimized:   {} in {:?}", result, duration);
        
        println!();
    }
}

fn main() {
    // Fibonacci benchmarks
    DpBenchmark::benchmark_fibonacci(30);
    DpBenchmark::benchmark_fibonacci(40);
    DpBenchmark::benchmark_fibonacci(50);
    
    // Coin change benchmarks
    let coins = vec![1, 3, 4, 5];
    DpBenchmark::benchmark_coin_change(&coins, 100);
    DpBenchmark::benchmark_coin_change(&coins, 1000);
    
    // LCS benchmarks
    let s1 = "ABCDGHIJKLMNOPQRSTUVWXYZ";
    let s2 = "AEDFHIJKLMNOPQRSTUVWXYZ";
    DpBenchmark::benchmark_lcs(s1, s2);
    
    // Knapsack example
    let items = vec![
        Item { weight: 10, value: 60, name: "Item1".to_string() },
        Item { weight: 20, value: 100, name: "Item2".to_string() },
        Item { weight: 30, value: 120, name: "Item3".to_string() },
    ];
    
    let (max_value, selected) = Knapsack::selected_items(&items, 50);
    println!("=== Knapsack Example ===");
    println!("Maximum value: {}", max_value);
    println!("Selected items:");
    for item in selected {
        println!("  {} (weight: {}, value: {})", item.name, item.weight, item.value);
    }
}
```

## Running the Code

To run this complete example:

1. Create a new Rust project: `cargo new dynamic-programming-examples`
2. Replace the contents of `src/main.rs` with the code above
3. Run with: `cargo run --release`

The `--release` flag is important for accurate performance measurements.

## Key Rust Patterns Demonstrated

1. **Error Handling**: Using `Option<T>` for cases where no solution exists
2. **Memory Management**: Efficient use of `Vec` and `HashMap` for memoization
3. **Borrowing**: Proper use of references to avoid unnecessary clones
4. **Generics**: Type-safe implementations that work with different data types
5. **Testing**: Comprehensive test suites for all implementations
6. **Performance**: Benchmarking code to measure real-world performance

This implementation provides a solid foundation for understanding and implementing dynamic programming solutions in Rust, demonstrating both the theoretical concepts and practical performance considerations.
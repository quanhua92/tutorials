# Lua Scripting: Server-Side Logic in Redis

**Source:** [07-lua-scripting.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/07-lua-scripting.rs)

## The Core Concept: Why This Example Exists

**The Problem:** Sometimes you need to execute complex logic that involves multiple Redis operations atomically, or you need to reduce network round-trips for computational tasks. Sending multiple commands from your application can be slow and non-atomic, especially when the logic depends on intermediate results.

**The Solution:** Redis allows you to execute Lua scripts server-side, providing atomic execution of complex operations. Scripts run in Redis's single-threaded environment, guaranteeing atomicity and consistency. Fred provides both low-level script execution (`EVAL`/`EVALSHA`) and high-level utilities (`Script`, `Function`, `Library`) that handle script caching and management automatically.

Think of Lua scripts like stored procedures in a database - custom logic that runs close to the data, reducing latency and ensuring atomicity.

## Practical Walkthrough: Code Breakdown

### Basic Script Execution

```rust
static SCRIPT: &str = "return {KEYS[1],KEYS[2],ARGV[1],ARGV[2]}";

let hash = fred_utils::sha1_hash(SCRIPT);
if !client.script_exists::<bool, _>(&hash).await? {
  let _: () = client.script_load(SCRIPT).await?;
}

let results: Value = client.evalsha(&hash, vec!["foo", "bar"], vec![1, 2]).await?;
```

This demonstrates the standard Redis script pattern:
- Calculate the SHA1 hash of your Lua script
- Check if the script is already loaded on the server
- Load the script if it doesn't exist  
- Execute with `EVALSHA` using the hash, keys, and arguments

**Why use EVALSHA vs EVAL?**
- `EVALSHA` only sends the hash (faster, less bandwidth)
- `EVAL` sends the entire script each time (simpler, but slower)
- Redis caches scripts internally, so `EVALSHA` is preferred for repeated execution

### Script Arguments and Keys

```rust
let results: Value = client.eval(SCRIPT, vec!["foo", "bar"], vec![1, 2]).await?;
```

Redis scripts receive two types of arguments:
- **KEYS:** Redis key names that the script will access
- **ARGV:** Values or parameters for the script logic
- This separation helps Redis cluster routing - keys determine which node runs the script

### Using Fred's Script Utilities

```rust
let script = Script::from_lua(SCRIPT);
script.load(&client).await?;
let _result: Vec<Value> = script.evalsha(&client, vec!["foo", "bar"], vec![1, 2]).await?;

// Automatic retry if script isn't loaded
let (key1, key2, arg1, arg2): (String, String, i64, i64) = script
  .evalsha_with_reload(&client, vec!["foo", "bar"], vec![1, 2])
  .await?;
```

Fred's `Script` type provides convenience methods:
- `from_lua()` creates a script object and calculates its hash
- `load()` ensures the script is loaded on the server
- `evalsha_with_reload()` automatically retries with `SCRIPT LOAD` if the script isn't found

### Redis Functions (Modern Alternative)

```rust
let echo_lua = include_str!("../tests/scripts/lua/echo.lua");
let lib = Library::from_code(&client, echo_lua).await?;
let func = lib.functions().get("echo").expect("Failed to read echo function");

let result: Vec<String> = func.fcall(&client, vec!["foo{1}", "bar{1}"], vec!["3", "4"]).await?;
```

Redis Functions (introduced in Redis 7.0) offer an improved scripting model:
- Functions are organized into libraries
- Better development and debugging support
- Persistent across server restarts (unlike EVAL scripts)
- Support for different scripting languages beyond Lua

## Mental Model: Thinking in Redis Scripting

**The Database Stored Procedure Analogy:** Redis Lua scripts work like stored procedures:

```
Without Scripts:                 With Scripts:
                                
Client → GET key1 → Redis        Client → EVALSHA → Redis
Client ← value1  ← Redis         Client ← result ← Redis
Client → GET key2 → Redis                ↑
Client ← value2  ← Redis           Script runs atomically:
Client → logic                     - GET key1  
Client → SET key3 → Redis          - GET key2
Client ← OK      ← Redis           - logic
                                   - SET key3
3 round trips                      
Non-atomic                       1 round trip
                                 Atomic
```

1. **Server-Side Execution:** Scripts run inside Redis, eliminating network latency for complex operations involving multiple keys.

2. **Atomic Execution:** All script operations happen atomically - no other Redis commands can execute while your script runs.

3. **Reduced Network Traffic:** Send one script call instead of multiple individual commands.

**Why Redis Scripting is Designed This Way:**

- **Performance:** Eliminates network round-trips for multi-step operations
- **Atomicity:** Guarantees consistency for complex operations
- **Flexibility:** Full programming language (Lua) for complex logic
- **Efficiency:** Scripts are compiled once and cached

**Common Scripting Patterns:**

1. **Conditional Operations:** 
   ```lua
   if redis.call('GET', KEYS[1]) == ARGV[1] then
     return redis.call('SET', KEYS[1], ARGV[2])
   end
   ```

2. **Multi-Key Operations:**
   ```lua
   local sum = 0
   for i = 1, #KEYS do
     sum = sum + redis.call('GET', KEYS[i])
   end
   return sum
   ```

3. **Rate Limiting:**
   ```lua
   local current = redis.call('INCR', KEYS[1])
   if current == 1 then
     redis.call('EXPIRE', KEYS[1], ARGV[1])
   end
   return current
   ```

**Script Best Practices:**

- **Keep Scripts Fast:** Long-running scripts block Redis (single-threaded)
- **Use KEYS and ARGV:** Don't hardcode key names (breaks cluster routing)
- **Handle Errors:** Check return values and handle edge cases
- **Cache Scripts:** Use `EVALSHA` for repeated execution

**EVAL vs EVALSHA vs Functions:**

| Method | Use Case | Pros | Cons |
|--------|----------|------|------|
| EVAL | Development, one-off scripts | Simple to use | Bandwidth overhead |
| EVALSHA | Production, repeated execution | Efficient | Requires cache management |
| Functions | Modern Redis (7.0+) | Persistent, organized | Newer feature |

**Script Security Notes:**
- Scripts run with full Redis privileges
- Be careful with user input in scripts  
- Scripts can access all Redis commands
- Consider script timeouts for protection

**Further Exploration:** Create a script that implements a distributed lock or counter with expiration. Try using Redis Functions to build a library of related operations. Experiment with scripts that operate on multiple data types (strings, hashes, sets) in a single atomic operation.

This example demonstrates how Lua scripting extends Redis from a simple data store to a platform for atomic, server-side computation, with Fred providing both low-level control and high-level convenience features.
# The Core Problem: The Cost of Copying

## Why Copying Is Expensive

Imagine you're working with a massive database table containing millions of customer records. Your application needs to create a "snapshot" of this data for analysis, but you also need to keep the original untouched for ongoing operations.

The naive approach is straightforward: make a complete copy of the entire dataset. But this creates several problems:

1. **Memory Explosion**: You now need double the RAM - one copy for the original and one for the snapshot
2. **Time Penalty**: Copying millions of records takes significant time, blocking other operations
3. **Waste**: In many cases, the copy remains unchanged, making the expensive duplication pointless

## The Real-World Impact

Consider these scenarios where copying creates genuine pain:

### The Photography App
A photo editing app loads a 50MB RAW image. When a user wants to experiment with filters, the app creates a copy so the original remains untouched. But copying 50MB for every "what if" experiment quickly exhausts device memory.

### The Configuration Manager
A system configuration contains thousands of settings. When a service needs to modify one setting, it first copies the entire configuration. But 99% of those settings never change, making the full copy wasteful.

### The Database Transaction
A database needs to provide isolation between transactions. When Transaction A reads data, it should see a consistent snapshot even if Transaction B is making changes. Creating full copies for each transaction would be prohibitively expensive.

## The Core Challenge

The fundamental problem is this: **We need the semantic behavior of copying (isolation, safety, independence) without the performance cost of actually copying data.**

We want to have our cake and eat it too - the safety of separate copies with the efficiency of shared data.

This is exactly what Copy-on-Write solves: it gives us the illusion of independent copies while sharing the underlying data until the moment someone actually needs to make changes.
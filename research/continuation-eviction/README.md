# Continuation eviction

Investigate compiler-generated safe points that serialize logical program counters and live locals when an async operation waits. Arbitrary native-stack capture is excluded. The goal is to release the complete guest store while preserving durable workflow semantics.

# Backend conformance suite

Every execution backend must pass the same cases:

1. scalar, list, record, variant, option, result, future, and stream contract values,
2. domain-error preservation,
3. platform-error separation,
4. deadline and cancellation propagation,
5. CPU and memory exhaustion containment,
6. capability denial and handle expiration,
7. state conflict handling,
8. effect idempotency identity preservation,
9. local/remote semantic equivalence,
10. trace and hierarchical budget propagation,
11. revision and route-generation pinning,
12. cell cleanup after success, trap, cancellation, and timeout.

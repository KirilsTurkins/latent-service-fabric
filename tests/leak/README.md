# Resource leak tests

The completed Phase 1 [measurement suite](../../docs/testing/phase-1-measurements.md)
retains finite mixed-workload reclamation and dormant-catalog observations;
the [extension report](../../docs/phase-1-extension-completion.md) adds source-specific
memory/ownership comparisons. Those results do not prove arbitrary-duration leak
freedom. Phase 2 adds a predefined
[32-release resource profile](../../docs/testing/phase-2-resource-profile.md) and
focused raw-cache, native-image, compiler, audit and coordinator ownership tests;
the [completion report](../../docs/phase-2-completion.md) distinguishes measured
RSS from actual owner retirement. The target matrix below also includes later-phase providers,
blobs and state transactions.

After repeated activation cycles, verify bounded resident memory, virtual memory, file descriptors, sockets, handles, timers, worker threads, cells, provider leases, temporary blobs, state transactions, and telemetry buffers.

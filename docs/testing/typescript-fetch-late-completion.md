# Late Fetch completion

This separate programme exercises ordinary global Fetch and AbortController in
the existing buffered profile. A real peer holds response headers or a partial
body. The guest aborts after at least one second, requires the exact caller's
reason, and stays alive for another three seconds. The controller releases the
peer after two seconds; it must complete both real responses. The original
public promise must still have one rejection and no resolution.

Bootstrap, both held responses and a fresh invocation use the original
16-task, 16-queue, 64-native profile, one-request budget, original HTTP provider
limits and node/request deadlines. Each result requires a known outcome,
reaped caller and zero physical owners. The installed node and peer must shut
down cleanly. Signing, captured source, component and historical native-product
identities remain separately checked.

The programme observes completion after public rejection and fresh module state
after retirement. It does not observe every intermediate admission refund,
prove all cancellation races, or establish fresh cross-tenant state. The latter
requires a separate genuine tenant-neutral signing and admission programme.

Source controls and pinned type checking pass; actual signed execution is
pending. Existing Fetch, client, buffered-body and resource-limit programmes
retain their separate results and are not silently replaced by this slice.

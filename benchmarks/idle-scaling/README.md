# Dormant release scaling

Phase 1 measured actual 100,000-registration catalogs, and the extension measured distinct/shared catalog memory. See the [completion review](../../docs/phase-1-completion.md) and [extension results](../../docs/phase-1-extension-completion.md) for exact populations and resource limits. The variants below remain the broader benchmark specification.

## Required metrics

- `registered_releases`
- `process_count`
- `thread_count`
- `socket_count`
- `cell_count`
- `rss_bytes`
- `route_lookup_p99_micros`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths

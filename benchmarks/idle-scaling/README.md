# Dormant release scaling

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

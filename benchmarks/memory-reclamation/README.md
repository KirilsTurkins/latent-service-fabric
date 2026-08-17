# Memory return after activation bursts

## Required metrics

- `baseline_rss_bytes`
- `peak_rss_bytes`
- `post_gc_rss_bytes`
- `retained_cache_bytes`

## Required variants

- cold artifact cache
- warm raw artifact cache
- warm AOT cache
- mapped/prepared cache where applicable
- success and bounded failure paths

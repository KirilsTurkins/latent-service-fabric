# Rejected optimization reference attempt

This diagnostic archive is **not a qualified performance baseline**. All seven
alternating pairs completed, but the recorded aggregate correctly reports
`status: failed`. The 88,326 attempts, 245 process receipts, original output and
executables remain byte-for-byte intact; no failed cases were replaced.

The measured source was `7857e6c` (the exact commit and tree are in
`aggregate.json`). There were no incorrect workload results. The LSF
`cache-working-set` case had 269 successful measured calls and 431 transport
failures out of 700, plus 18 warmup transport failures. Every other ordinary
measured workload succeeded. Tight-budget and saturation failures remain in the
raw population.

The cache test requested a 5,000 ms budget, exactly the node's configured maximum.
The client rounds the absolute deadline upward to a whole millisecond; the
server's earliest wall-clock sample rounds downward. At a fractional tick this
can project 5,001 ms into the future, causing the server to reject the deadline
with gRPC `InvalidArgument`. This is a benchmark configuration error, distinct
from the measured workload's correctness.

The corrected preset uses the ordinary 1,000 ms budget and has a regression test
against the actual node configuration. The entire seven-pair population was
repeated independently. The accepted reference has its own source identity and
plan hash; this rejected population is never pooled into it.

`raw-evidence.manifest.json` binds every archived file and the archive's checksum.
Shape-only archive verification preserves these diagnostics without claiming
they pass the publication gate. `replay-source-7857e6c.tar.gz` contains the
matching committed Python replay tools and schemas. Extract it into a separate
directory and extract the verified raw archive into another directory, then run:

```sh
python3 tools/validate_optimization_evidence.py /path/to/raw/suite.json \
  --check-aggregate /path/to/raw/aggregate.json
```

The expected result is the exact retained aggregate with `status: failed` and
exit status 1. The current validator intentionally rejects the obsolete preset;
it cannot be used to relabel this population as the corrected reference.

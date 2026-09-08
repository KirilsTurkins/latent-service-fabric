The two `cache_behavior_*.json.gz` files are debug-only functional parser fixtures
from the #102 COMMON collector. They contain the original observed event graph
and its six fixture metadata/component inputs, with no collector executable.
They are not release benchmark evidence and do not contain the official build,
parent-process or host provenance required by the suite validator.

The test adapter supplies the omitted, known 100 Hz task-clock resolution in
memory. Each test reconstructs the inputs in a temporary directory and hashes
them again before replay. The candidate fixture includes the actual unique
runtime ledger; the control fixture reports that ledger as unavailable. Each
retains 80 offers, including two concurrent debug transport failures and the
intentional invalid component failure. Tests must preserve those populations.

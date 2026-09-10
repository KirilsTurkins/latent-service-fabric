# Original catalog compatibility fixtures

Captured from the original catalog compiler at `2a3bd3c753ff17b2adb8e27e8bd2fa580c52f46b` before the compact-record implementation. The separate test checkout added only a fixture capture test. One named test passed; no production code changed during capture.

The fixed catalog has generation 9, timestamp 1234567890000, two releases, three deployments, Alice/Bob scopes, mixed default weights, named routes, and escaped/Unicode annotations. The fixtures retain exact canonical V2 persistence and snapshot JSON bytes, plus 36 weighted selections across default/explicit-default/named routes and empty/Unicode/delimiter-bearing keys. Three lookup errors retain code, message, and retryability. The ordinary regression test only compares against these retained values; it does not regenerate them.

These are small correctness fixtures, not performance measurements. Fixture hashes and capture source identity are in `capture-receipt.json`.

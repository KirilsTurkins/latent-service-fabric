# Original Go retained-node invocation failure

The original Go component compiled and passed all five initial scenarios,
including the expected denied-capability trap and a subsequent fresh success.
After confirmed shutdown and restart, the original greeting invocation trapped.
It selected the same publication, revision, component and deployment generation.
The original admission grants were unchanged. Cleanup confirmed owned process
reaping and zero provider counters.

The original [probe](probe.json), [scenario report](node-tests.json) and
[retention receipt](receipt.json) remain failed evidence. The branch head was
`55c79dc8f792203f7015af656a6dd133cadd24b9`; GitHub tested merge source
`0e1ebad6234f7f3a93410cf356db69ec2bb2aebc` in run `36862212377`,
job `110368916832`. Artifact `11169635043` has immutable ZIP digest
`b9b1fe51b4bb694f22ea0b1640c2d807c8773765be57c51dd9fe7fef65864344`.

The source probe previously kept only the public trap code, then reaped its
owned node. It did not retain the activation's privileged producer diagnostic.
The cause cannot be inferred from this report. The new observer makes one
bounded supported activation-tree request per original failed activation,
using the original operator credentials and parent deadline before cleanup.
At most eight original IDs and sixteen seconds are observed. Missing history
keeps an explicit fixed unavailable reason. No invocation or deployment is
retried and neither existing success assertion changes.

All 44 controller cases passed on actual Linux with Python 3.13.5 and no skips.
The 41 historical cases, fixture hashes and execution guards remain unchanged.
These tests qualify the observer, not the original guest failure's cause or a
successful signed node campaign. Original source-node evidence is explicitly
unauthenticated, not a clean-host packaged qualification.

A read-only Rust comparison used run `36861863143`, event artifact
`11169709935` (ZIP digest
`4d31c3cd12f717004e019d68a99753149e4b7130bdc68561a281120de9b99f0c`).
Its retained event invocation returned success with an unexpected payload;
its ordinary Rust greeting, shipping and word-count restart cases passed.
That event failure has a distinct observed outcome and does not establish a
shared cause for this Go trap.

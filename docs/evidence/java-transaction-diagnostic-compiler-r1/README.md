# Actual unsigned diagnostic Java component compilation

The explicit single diagnostic component plan compiled successfully from clean
source `aab172ba3df2c4d7c6f6335b074400432055f174`. Its original process reported
component SHA256
`0640b1bb0a28a7cc80b785efd6c1a3c8d55612e0a70759be2f2a400268dec20f`,
**1,013,874 bytes**, compiler phase **170.156894 seconds** and completed
controller process **202.413667 seconds**, exit zero. The original stderr is
empty. This is actual TeaVM/C/WASI component compilation, separate from the
earlier helper-only [JVM vectors](../java-transaction-diagnostic-source-r1/receipt.json).

The bounded unprivileged process used one CPU, 4 GiB memory and 256 PIDs in the
recorded OS-only Ubuntu/Python image. It consumed the original authenticated
Java developer bundle from immutable producer
`761172002e4a4d02102f8c757235b888fe4859e1`, archive
`sha256:37e7225616c22665f39b2c50348be402cafb5cf087189eac77bef73ed70721c9`.
The JDK/Gradle/WASI tool roots were mounted read-only; the complete original tool
closure was verified before and after compilation at
`sha256:46190f6e208fc5a0046522f2783adcc0752a7bc762db7a8b507e198fd064883b`,
2,902,802 inventory bytes. The original executing program and selected inputs
are preserved alongside [receipt.json](receipt.json). No native runtime was
compiled and none of the five original `ff9ecd07` components was replaced.

Docker's engine subsequently failed during its own disk provisioning. The
component, full source archive, generated C and inner compiler logs had not yet
been exported; the original wrapper stdout, stderr, command, process receipt and
selected tool identities were already retained on the host. Their exact bytes
are fixed in [file-inventory.json](file-inventory.json). The original component
identity is therefore measured, but the component export is explicitly
unavailable. No new empty volume, substituted component or rebuilt artifact is
labelled as this original receipt.

Compilation establishes no signature, admission, namespace/provider authority,
durable commit, guest freshness, fuel-exhaustion or cancellation evidence. All
runtime qualification flags remain false. The separate
[fault-capsule guide](../../testing/java-transaction-diagnostics.md) specifies
the actual signed runtime oracles still required: original staging consumption,
known-not-committed/abort evidence, unchanged query and zero external PUTs.

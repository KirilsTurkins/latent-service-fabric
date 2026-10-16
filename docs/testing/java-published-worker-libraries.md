# Unchanged Java library worker qualification

Status: original-library JDK reference controls and qualifier tamper controls
pass. Actual TeaVM/C compilation and signed component execution remain pending.
This is a slice of [#741](https://github.com/KirilsTurkins/latent-service-fabric/issues/741)
and [#682](https://github.com/KirilsTurkins/latent-service-fabric/issues/682).

The selected fixture calls Commons Lang 3.14.0
`CallableBackgroundInitializer` without an external executor. Its
[unchanged upstream implementation](https://github.com/apache/commons-lang/blob/rel/commons-lang-3.14.0/src/main/java/org/apache/commons/lang3/concurrent/BackgroundInitializer.java)
creates an ordinary fixed executor and shuts that executor down in its own
worker's `finally`. The other library is Hutool Core 5.8.40:
[`ThreadUtil.execAsync(Runnable, false)`](https://github.com/dromara/hutool/blob/5.8.40/hutool-core/src/main/java/cn/hutool/core/thread/ThreadUtil.java)
creates and starts an ordinary Java thread. The application supplies work and
observes its current thread; it does not replace either library's worker,
executor, bytecode or class names and adds no SDK shutdown call.

The qualifier uses normal Java add, native Maven resolution, exact candidate
review, dependency verification and offline classpath materialization. It checks
the original upstream archive digests before any reference class loading and
rechecks the reviewed source, original archives, selected archives and classpath
receipt after compilation. The normalized classpath preserves the production
Java archive selection rules and all original class names. Build provenance for
the signed fixture includes the tested capture and compiler receipt.

| Library | Original archive SHA-256 |
| --- | --- |
| Commons Lang 3.14.0 | `7b96bf3ee68949abb5bc465559ac270e0551596fa34523fddf890ec418dde13c` |
| Hutool Core 5.8.40 | `d6bedc908cba480cd12dbe6f8422fa60c0da31030b58a68c3c077f555fc0cbbc` |

Four modes cover each library independently, both overlapping, and original
Commons failure propagation alongside Hutool worker interruption. Workers use
the actual typed runtime wait. Root progress and thread-local isolation must
remain observable while the workers are pending. The private JDK control
interprets that host wait as noninterruptible until completion and preserves a
Java interrupt flag; it is a reference interpretation, not canonical execution.

The maintained Linux gate compiles the actual application and both unmodified
libraries using the explicit
[`teavm-activation-fibers-io-v1` profile](java-fiber-host-io.md), then executes all
four modes in three fresh signed activations. The existing 64 MiB memory, one
billion fuel, 120-second activation and two-timer ceilings remain. Existing node
idle checks must pass after each invocation. All old Java workflow commands and
the original 55-minute enclosing job remain.

Local source controls pass, including the three four-mode original JAR/JDK
reference iterations, pinned WIT/C ABI generation and compilation of all selected
SDK and library Java sources. Native component execution, the broader runtime failure,
cancellation and isolation matrix, and paired cost measurements remain required
before the language ticket can close. These libraries do not establish ordinary
default HTTP overlap or general compatibility of every API they publish.

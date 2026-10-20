# Ordinary Java classpath resource conformance

The maintained [greeting](../../examples/java-resource-conformance/Capsule.java)
uses two real local JARs absent from the dependency catalogue. The parent calls
the transitive child through unchanged Java code. Normal `add-local`, resolve,
exact lock review and content-addressed capture bind both archives and the
child's resource entries. The original source, class and JAR directory is then
removed. The component is built offline against the verified compiler cache;
the application needs no resource callback or custom runtime bridge.

The child uses ordinary `Class.getResourceAsStream` and
`ClassLoader.getResourceAsStream` for UTF8 text containing NUL, opaque binary,
an empty file, a missing name and independent stream positions. Closing one
stream must preserve the other. These are fresh `ByteArrayInputStream` values;
their standard close method need not invalidate the closed stream. An
application-declared Unicode logical path is tested separately. The captured
JAR archive path grammar remains unchanged; no wider archive-name acceptance is
implied. A null name must preserve `NullPointerException`.

The same ordinary export returns `System.currentTimeMillis()` and two ordered
`System.nanoTime()` longs as decimal strings. The wall value must exceed32 bits
and lie between host observations. The monotonic origin is activation-local;
the receipt states whether the actual sample exceeds32 bits, without pretending
a short activation demonstrates a long interval. No sleep, test clock or host
override is added. The existing int64 producer mapping and millisecond wall
resolution are preserved. The
[existing .NET wall observation](../testing/evidence/dotnet-utc-resource-control-2026-10-12.json)
already records full-width ticks and Unix milliseconds and is not rerun here.

The normal55-minute Java parent and its original jobs, commands and deadlines
remain unchanged. A separate20-minute child consumes that run's authenticated
public native products and four companion components. It compiles one fresh
resource greeting and runs the original29 signed outcomes plus ten data,
clock, explicit-fixture-trap and fresh-after-trap calls. Each added invocation
requires the original CPU/memory bounds, no outbound/log/effects, a known reaped
outcome, zero active provider owners and physical retirement. Normal package,
demo signing, admission and CLOCK grants remain mandatory; no filesystem or
extra runtime authority is introduced.

Run the finite source controls with:

```powershell
python -B -m unittest tools.tests.test_java_resource_conformance -v
```

Those controls do not establish a signed pass. The new programme is pending
actual component execution. Compiler-cache acquisition may compile its ordinary
warm-up greeting; that output is separate from the observed resource component.
An explicitly historical diagnostic replay must retain its original native and
companion ancestry and cannot manufacture a current normal qualification.
Concurrent callbacks, root cancellation, pending flush, cross-tenant state and
the full six-language resource/error matrix remain open under #681/#736.

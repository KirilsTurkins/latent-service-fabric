# Java bounded standard entropy

The candidate `lsf.java.bounded-entropy.v1` port installs SDK-owned method bodies
on the pinned TeaVM standard `java.security.SecureRandom` class. Ordinary
application and dependency imports stay unchanged. The compiler verifies the
original class layout, preserves the original model and SDK template owners,
and rejects an unknown or repeated replacement. Caller package names do not
select compatibility.

The normal captured WIT must declare `latent:random/random@0.1.0`; the operator
must separately supply its approved provider, binding, policy and finite budget.
The port adds no import or grant. Without the declaration, a nonempty read throws
`ProviderException` with `bounded-entropy-capability-not-declared`. The compiler
does not retain the C backend's deterministic `Random` fallback for SecureRandom.

| Standard API | Finite behavior |
| --- | --- |
| Default constructor | No entropy read or build-time initialization. |
| `nextBytes`, `generateSeed`, static `getSeed` | At most 4096 bytes per call from the declared bounded entropy provider. Empty reads require no host call. |
| `nextInt`, `nextLong`, `nextBoolean`, `nextFloat`, `nextDouble` | Ordinary numeric distributions consume the same provider through the standard virtual methods. No SDK random seed or shared generator is retained. |
| Provider errors | Invalid length, exhausted budget and unavailable source throw distinct `ProviderException` codes. Failed reads preserve the caller's buffer; temporary provider bytes are wiped. |
| Algorithm selection | `getAlgorithm()` reports `LSF-BoundedEntropy`; `getInstance` accepts that exact name. Other named algorithms fail with `NoSuchAlgorithmException`. |
| Caller seeds / reseed | Seeded construction, byte seeds, nonzero long seeds and reseed throw `UnsupportedOperationException`. A zero long seed has no effect, including the superclass-construction call. |
| Provider registries, parameter objects, arbitrary algorithms, serialization and other unlisted APIs | No compatibility claim; ordinary compiler diagnostics remain authoritative. |

Negative seed lengths and null buffers retain their standard argument failures.
No partial output, uncharged worker, entropy handle, application-owned entropy
source, ambient OS import or filesystem fallback is installed. Entropy bytes
are acquired during invocation; compiler analysis loads only verified tooling
models and does not execute application or provider initialization. Runtime
clock support remains independent of application entropy authority.

The [local evidence](../testing/evidence/java-standard-entropy-source-2026-10-16.json)
records the actual locked class model, 245 host source checks, real WIT/C binding
generation and nine reference-JDK observations. These controls do not establish
component execution. The existing signed Java SDK gate additionally selects
12 real component invocations against the system entropy provider, checking its
original generated-byte counters, per-call and per-activation limits, failed
buffer preservation, fresh statics and original-owner retirement. Its existing
direct-binding cases remain unchanged. The corrected finite signed programme
passed as recorded below; this does not complete #681 or the concurrent #741 matrix.

The [first signed attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38857653138/job/116832770215)
on immutable `5ec238dd` compiled the component and passed eleven SDK cases. The
numeric entropy case returned its expected result but failed the provider counter
assertion: 27 bytes were generated, while the test expected 24. The pinned TeaVM
`RandomGenerator.nextBoolean()` delegates to `nextInt()`, consuming four bytes.
The complete sequence consumes exactly 4 + 8 + 4 + 3 + 8 = 27 bytes. The corrected
assertion retains that exact total, and the locked model control verifies the
inherited method's delegation. The JDK reference establishes numeric behavior,
not an identical entropy byte cost.

The corrected source `f2a6d762680f713051b3bb359ddf7727e6532cfe` passed the
[full native Java job](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38925592063/job/117056182241),
including all 12 signed standard-entropy invocations. PR #1042 merged as
`4f8ac14b82ebdfc52f3cd683a4a0706de99accfc`. This records that exact historical
source and programme; it does not rebind the native result to the current
integrated head or establish the remaining six-language, concurrent or
cross-tenant lifecycle matrix.

The supported and narrowed API behavior is described against the
[JDK SecureRandom contract](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/security/SecureRandom.html)
and the pinned
[TeaVM class library](https://github.com/konsoletyper/teavm/blob/0.15.0/classlib/src/main/java/org/teavm/classlib/java/security/TSecureRandom.java).

# TypeScript standard clock boundary

The maintained compiler supplies ordinary `Date` and `performance` calls beneath
unchanged application and captured dependency code. The explicitly selected
`spidermonkey-activation-promises-clocks-v1` and
`spidermonkey-activation-promises-clocks-imports-v1` profiles use the existing
typed wall and monotonic clock backend. Both exact clock imports must be
declared; operators must install their provider bindings, policies and grants.
Selecting a profile grants no clock or timer authority.

| Ordinary API | Selected behavior |
| --- | --- |
| `Date.now()` | Current authorized Unix milliseconds |
| `Date()` as a function, with any arguments | Current authorized wall-time string; Date ignores those arguments |
| `new Date()` | Current authorized wall time |
| `performance.now()` | Activation-relative monotonic milliseconds; the first sample is zero |
| `performance.timeOrigin` | Authorized wall-time origin from the existing engine backend |
| `new Date(explicit arguments)`, `Date.parse`, `Date.UTC` | Ordinary deterministic Date behavior, including invalid `new Date(undefined)` |

Application clock reads without an approved profile throw
`unsupported:standard-clock-without-approved-profile`. They do not return a
frozen build timestamp. Explicit Date arguments and static parsing remain
available without clock authority. Provider errors preserve their original
identity; the wrapper does not retry or synthesize a timestamp.

The application-realm guard is installed after compiler/engine bootstrap. It
refuses snapshot-time direct or captured-reference clock observations before
accessing a provider. Existing Console-selected activation initialization stays
separate. This does not defer every top-level clock-using library initializer or
permit mutable request identity in a shared snapshot. Engine core bytes and
their original source/input receipt are not rewritten by this compiler guard.

The finite component campaign passed at source
`e63b31cb0670ef97b614c65c8dbd7f9672b879d8` in
[run39346830485/job118381347093](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39346830485/job/118381347093). Its default-false
`qualify-standard-clocks` manual selection has a separate 20-minute job. It
authenticates the original clock-engine core/receipt and all 31 SDK inputs, plus
the historical native five and three unchanged companion packages. It builds
only a new clock greeting and an unselected word-count probe with the maintained
compiler. An ordinary outside library and transitive UTF-8/binary resources are
captured through normal npm authoring, exactly reviewed, then their original
source directory is removed before compilation.

The passed programme retains the original 27 and adds three before-guest
missing-grant denials, seven unselected Date/performance values, six selected
clock/resource values and two trap/fuel cases followed by fresh success. All 47
outcomes were known/reaped and retained their original budgets and cleanup
checks. The 20 new clock outcomes had zero outbound/child/log effects. All 26
provider-idle samples had zero active owners, 41 physical samples were retained,
and node shutdown was clean/reaped. Two separate
actual compiler attempts refused direct and captured-reference clock reads
at snapshot creation. Mocked source/protocol checks are not evidence that these
components have executed.

The first completed component in the campaign exposed unused readiness imports
pruned by the encoder. For the exact authenticated clock-engine envelope, the
final parser comparison permits only omission of `observe`, `wait-for`,
`wait-until` and their exclusive `phase`/`observation` types. The complete
original activation ABI digest is still pinned, including omitted declarations;
all eight retained activation functions, three retained types, both complete
clock interfaces and application exports must match exactly. A different core,
source envelope, interface, signature or added import is refused. This is
compiler graph reconciliation, not signed runtime qualification.

For the bounded prepared-input campaign:

```bash
gh workflow run typescript-guest.yml --ref YOUR_REVIEWED_BRANCH \
  -f qualify-standard-clocks=true
```

Only fixed public source/package layers and explicitly identified native/engine
products are acquired. Original native compiled source remains historical; a
newly vendored workspace is not relabelled as their producer. This path neither
rebuilds native hosts nor changes public error disclosure, signing or admission.

This advances the TypeScript clock portion of [issue #681](https://github.com/KirilsTurkins/latent-service-fabric/issues/681).
It does not qualify timers, durable schedules, unsupported filesystem/scratch,
cross-tenant/concurrent lifecycle behavior or the whole six-language facility
matrix. See the separate [entropy boundary](typescript-standard-entropy.md).

The first signed clock attempt at source `cfc0e4805bc96b8756d4855d4729cb3d33c447ac`
compiled both fresh components and passed both snapshot-refusal controls, then
was rejected as `corrupt-artifact` before guest execution. The fixture had
installed clocks but omitted the existing activation-runtime owner required by
the native engine. Its unchanged async cancellation builtin is rejected when
that owner/profile is absent. The corrected campaign installs the same bounded
owner and eight-operation explicit runtime-support grant used by the maintained
Fetch programme before testing the three missing-clock cases. No global engine
feature or limit was relaxed. The corrected run passed all 47 signed outcomes.
The [compact source-bound observation](../testing/evidence/typescript-standard-clocks-signed-2026-10-20.json)
retains exact results, component/recipe identities, two snapshot refusals and
explicit historical native/engine ancestry. Its original native normal receipt
has 30 outcomes and remains unchanged; this separate campaign repeats the
original 27 plus its 20 clock outcomes. These finite results do not qualify
scratch storage, concurrent/cross-tenant lifecycle or the full issue.

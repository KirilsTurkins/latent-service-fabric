# Explicit Java HTTP phase adapter

`lsf.java.httpurlconnection.phase-timing.v1` selects an additive compiler-owned
`HttpURLConnection` variant for `latent:http/phase-timing@0.4.0` and host ABI V7.
It requires the existing explicit `teavm-activation-fibers-io-v1` runtime,
activation/monotonic imports, and the new phase interface. Transaction authority
cannot be combined with this profile. The existing streaming profile, SDK client
source, frozen 0.3 interface and default host ABI remain unchanged.

The compiler verifies the exact captured `Connection.java` preimage and derives
only its selected owned copy. Both source identities enter the HTTP profile
receipt, together with the recipe, source and final component identities. A
changed SDK preimage or staged copy refuses before replacement.

Nonzero `setConnectTimeout` values select the provider's actual queue/DNS/TCP/TLS
connection-establishment boundary. Nonzero `setReadTimeout` values select response
headers and each subsequent provider read, independently. Zero remains an absent
phase timer. Neither setter extends or replaces the original activation deadline.
Only the new typed connect/read timeout outcomes become `SocketTimeoutException`;
original root interruption retains its root outcome or `HttpFailure` code and
cannot satisfy a phase-timeout assertion. A timed-out header operation retains its explicit uncertain-completion
cause. Failed operations preserve the first exception and never recreate or
replay an upload or body read.

Response-message metadata uses actual bounded Latin1 reason bytes: unavailable
is `null`, observed empty is `""`, and no status-derived phrase is synthesized.
The selected body owner is acquired before validating those bytes so a malformed
result closes that owner. Existing request/body/chunk bounds, redirect refusal,
header ownership and immutable views remain in force. HTTPS remains explicitly
unsupported; selecting this profile does not grant any destination or transport
authority.

Focused source controls and an installed-JDK reference exercise the actual derived
adapter against a modeled typed port. The reference checks 27 phase outcomes and
four legacy controls, including exception identity, root-error separation, timeout
options, reason bytes and body release. This is host adapter evidence. It does
not establish TeaVM compilation, canonical-ABI aliases, signed component execution,
physical provider retirement or whole-issue #688/#741 completion. Those require
the new V7 host and actual pending HTTP component programme; historical 0.3 native
products cannot qualify this profile.

The prepared public campaign uses one ordinary project capturing DavidWebb 1.3.0,
its transitive JSON dependency, and http-request 6.0. Both published clients use
their default timeout paths under the same selected profile; DavidWebb's nonzero
defaults are not replaced. Its other standard URLConnection
cases select explicit nonzero success, held-header and partial-body read expiry,
root deadline/cancellation separation and a fresh request. A Linux connect case
uses the same real full-accept-backlog premise as the maintained native ownership
test: one `listen(1)` listener and two bounded fixture-owned TCP connections.
They write no HTTP and do not warm or retry the guest. The guest's explicit
`connect()` must report the connect-specific timeout; returning from connect,
a read timeout, or a root interruption cannot satisfy that result. Separate
pending-connect cases preserve the root deadline/cancellation distinction.
The maintained campaign plans 16 signed invocations: eleven primary cases and
five fresh calls after terminal operations, with two separate zero-fuel authority
denials. The three connect cases own separate full backlogs, require a real
connecting-pool owner and issue no HTTP. The one-second connect timer leaves a
finite observation window; root-deadline cases retain the original three-second
root bound, and provider/activation ceilings are unchanged. The exact peer oracle
requires thirteen HTTP contacts, no secondary contact or mutation, physical zero
owners after each invocation, and a clean/reaped final node. Results, shutdown,
peer and product checks are retained separately before the compact summary.

V7 native producer `77bf0e3f3b68e17342b6146abd6f2de34a3efa00`, run
`39420914927` / job `118621322461`, completed successfully. Its five products,
eleven filtered controls, exact native sources and 114 compile materials are
authenticated separately from the current Java fixture/compiler source. The
consumer refuses a different native source or any extra/changed WIT, schema or
echo compile input; it does not rebuild native binaries or relabel the old a4
products. Actual TeaVM compilation and these signed Java outcomes remain pending.
The programme is a partial #688/#741 qualification, not whole-issue closure.

The first owning Java run `39426677454`, job `118640895893`, stopped before
TeaVM or signing: the existing binding reader rejected the canonical indirect
asynchronous C argument record. The pinned wit-bindgen 0.62 generator emits one
function-owned `*_args_t` record for multiple indirect arguments even with
`--no-sig-flattening`. The selected Java bridge now accepts only that exact
ordered value record and retains it in the existing pending-call heap until the
terminal subtask is taken; every input is decoded and released through its WIT
codec. Direct, synchronous and exported layouts keep their prior checks. Two
positive controls failed on the original reader; the targeted layout/lifetime
and malformed-input controls pass after the correction.

The fixture also uses the shared canonical-preimage projection for its old
HTTP dependency: only the eight legacy function declarations are removed.
Every nominal resource/type byte and the complete new phase interface remain
unchanged. This avoids implicitly requesting a second operational provider;
it grants no legacy operations. The corrected actual component campaign remains
pending, and the original failed run remains failure evidence.

The separately observed TypeScript consumer exposed an authoring check that still
expects the complete old callable interface. At that revision the Java phase campaign was held
until the shared exact nominal-owner packaging correction and its authenticated
new native products became available; no old provider grant is added to bypass it.

The shared nominal packaging correction is merged in `8e03a7cc`. Its exact
producer source `36eaed79dbd92cac12bad2dd1f52cd5d1acd525f`, run
`39430989809` / job `118655688632`, passed the original eleven native controls
plus two new nominal host/normal-authoring controls. Artifact `12269226324`
authenticates the five products and 114 compile materials. The new
`http_phase_native_products.py` authenticator is separate from the historical77
helper; all seven old controls remain and seven new controls are additive.
That Java campaign revision selected the 36ea tuple and required current native and
auxiliary source equality before compilation. The earlier failed Java run and
old 77 provenance are retained. Signed Java phase outcomes still require the
corrected next owning run.


An earlier campaign revision selected the independently authenticated producer
`6f5f180136d140ac670561695260f71514781015`, run `39443901256` / job
`118700610031`, artifact `12275691963` (66,080,276 bytes; SHA256
`fa6c846ffcf5f79b1153d60053aeb79f2e3495228f1c7c510159f7a2c072e399`).
Its normal five products passed 25 selected Rust controls and four Python graph
controls. The complete archive, native Git identity (3,312 files), all 114 compile
materials and all five product hashes were independently verified. The new
`http_tenant_native_products.py` helper has independent immutable pins; the old 77
and 36ea helpers and all their controls remain unchanged. Only native product
acquisition selects the new tuple. Current complete native and auxiliary source
identity must still equal the producer before any Java compilation.

The previous Java run `39438537720` stopped in ordinary Gradle Java compilation,
before TeaVM, signing or HTTP invocation: the pinned transitive org.json version
has checked JSONException signatures. The unmodified default-client success
body now resides in a private checked helper; only JSONException is wrapped in
an IllegalStateException with its original cause. A host JDK reference control
reproduced the old compilation error and verifies the corrected success/cause
and disconnect behavior. This does not constitute component execution.

After the original sixteen phase cases and two pre-guest grant denials, the
current campaign reuses that same freshly built default component for the
[twelve-outcome same-node tenant programme](java-http-tenant-isolation.md).
There is no second component compilation or native build, no timeout increase,
no change to the old case bodies and no HTTP alias. The finite programme requires
separate tenant HTTP installations and credentials, original operator isolation,
default Webb and HttpRequest success, pending read timeout/root cancellation,
foreign-origin zero contact and fresh state. Actual signed Java results remain
pending the next owning run; public transport SPI and whole #688/#741 completion
remain separate requirements.

The operational-authority correction subsequently selected producer
`8f7780dd0a35e3375524d72e7dfaddf847deaa5c` and preserved that authenticator as
an immutable historical tuple. Java run `39461289033` loaded its exact private
compiler JAR, then failed before a component existed in TeaVM's original-entry
liveness lookup. Corrected source `7bb87351a7c05cdf915c5a160f788803977be9ae`
failed in run `39463938701` while compiling three new IR-harness constructor
references. Neither IR control nor guest execution ran. Those references now use
the pinned API's `ValueType` overload; actual old/new IR remains required.

After the independent pending-wait observer merged into development, the
maintained campaign selects successful producer
`f9192fb5785ca7bed8b33dbb869b3d775b72ab4b` through the shared strict frozen-tuple
reader and `wait_runtime_native_products.py`. Run `39458247294`, job
`118750640204`, artifact `12282362053` built five products and passed 30 native
controls plus four Python controls. Its archive digest is
`d3942fea19d78c27aac37811fc7f9be32cc26fc76b95a92f98498c3d44162945`.
All current native source and 107 auxiliary inputs must still equal this exact
producer before and after Java compilation. The reader itself is a captured
campaign material. The old 77, 36ea and 8f helper files and controls remain
unchanged; no historical guest result is relabelled as current qualification.

Source `f267339b620446d5e6a4779dcc34c788e460adb8`, tested as the byte-identical
merge tree `5e515c23196465b683dbed5a136bc476e67d1a88`, passed both real JVM IR
controls and TeaVM C generation in run `39467113742`, job `118781269087`.
Artifact `12286760612` retains those logs and the next clang refusal:
`TimeZone.c:361` passes an integer temporary to a pointer-valued GC-root slot.
No component or guest invocation exists from that run. The separate phase-only
failure-context selection now adds exactly `c/j/u/TimeZone.c`, retaining its
bounded declarations and uses before temporary build cleanup. The original
two-file fixture selection, all byte/line bounds and clang acceptance remain
unchanged. No cast or compiler suppression is applied without that evidence.

Run `39471125675`, job `118795138952`, retained that exact context in artifact
`12286564077`. The integer array index is declared `int32_t`, loaded from an
integer array and then incorrectly registered as a GC root. Pinned TeaVM 0.15.0
`TypeInferer` starts its worklist only for ordinary graph edges, although array
element propagation uses a second graph. An array with only element-use edges
therefore leaves its primitive element classified as an unknown object.

The first private repair added that graph to the initial worklist condition.
Source `663ba30a99562d0c8b371d4838a15d48ee6893fa` passed both real original/private
JVM controls and C generation in run `39473963917`, job `118804988184`, artifact
`12288736711`. Those controls proved the original primitive-root defect and
preserved the actual object and nested-array roots. The component still failed
clang: its integer temporary was now inferred as an array pointer.

The next pinned-source boundary is coroutine restoration: `Fiber.popObject`
writes back to the original array variable with an erased object result. The
array-load reader then ignores its declared primitive element type. The repair
uses that type for primitive results and retains secondary-graph propagation
for object elements. An additional real IR control restores an array through
the exact `Fiber.popObject` signature, loads an integer and keeps it live across
a call. The old compiler must root that scalar; the corrected compiler must
preserve its integer type without registering it as a reference. The original
pinned source, private JAR, all eight replaced class identities, actual loaded
classes and every unrelated JAR entry remain checked. This new hosted control
and the signed Java programme are pending; no component pass or C warning
suppression is claimed.

The corrected restored-array control, C compilation, component assembly and
validation passed in run `39475616027`, job `118810665243`. Its strict WIT guard
refused the emitted surface. The two existing bounded WIT JSON logs were then
retained by run `39477502762`, job `118817154924`, artifact `12291420311`.
Normal component emission omitted exactly the unused legacy HTTP `response`
record; every nominal resource, phase operation, other import and export was
identical. The selected phase comparator now binds the complete declared
nominal-owner and phase graphs before permitting only that omission, followed
by full graph equality. Default HTTP 0.3 remains strict, as do altered source
records, resource owners, phase operations, exports and any further omission.
Real retained-pair and mutation controls cover that boundary. Signed Java
phase/default-client and tenant results remain pending.


Run `39480063296`, job `118825984972`, completed the repaired JVM IR controls,
C compilation, strict WIT comparison, component validation and normal package
assembly. Its retained build observation identifies a 17,034,179-byte component
`10997f52862068bc5570b33292ef4de56de3c3396f0324d8ba911d2a90fc56c5`.
Artifact `12290348244` retains all 38 public JSON/log members. The qualifier then
incorrectly applied the 4 MiB source-file reader to that component, before
signing or guest execution. It now hashes with the producer's existing 64 MiB
component bound, using the unchanged regular-file, mutation and exact digest
checks. Controls retain the original 4 MiB refusal, accept a 17 MiB component,
and reject altered profile/digest, over-64 MiB and nonregular inputs. No runtime
or application budget changes. The owning artifact additionally retains only
this public fixture's component and assembled package so a later reader-only
repair can reuse them. Signed client/deadline and tenant execution is pending.

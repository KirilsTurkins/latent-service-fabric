# Informational compatibility catalogue

The current [version 3 catalogue](v3/README.md) and its [JSON data](v3/catalogue.json)
publish eight finite package observations bound to 31 original public documents.
[Version 2](v2/README.md) and [version 1](v1/README.md) remain unchanged historical
editions; version 1 is the original Java-only edition. The [schema](v1/schema.json) describes their
machine-readable structure. They are optional documentation: dependency capture,
compiler selection, signing, admission and capability grants do not consume them.
An unknown coordinate has the same opportunity to build and execute as a listed
coordinate using the same implemented API/profile and explicit authority.

Read and verify the retained document bytes and entry bindings from a checkout:

```sh
python -m tools.compatibility_catalogue docs/compatibility-catalogue/v3/catalogue.json
python -m tools.compatibility_catalogue docs/compatibility-catalogue/v3/catalogue.json --json
```

The reader performs no network request, build, installation, grant or invocation.
Missing or tampered catalogue evidence fails this optional reader. It does not
change the normal build or runtime path. Structural separation is distinct from
the six-language actual-component catalogue-absence campaign required by #694.

Each entry binds a package coordinate, version and original artifact digest to
retained package metadata. Its key also binds the full captured graph,
features/configuration, source/component, compiler materials, tested engine
closure, runtime/backend, automatic platform transformations and WIT bindings.
Every binding identifies an exact JSON pointer and value digest inside a bounded
retained public document. Document records retain their original workflow source,
run, job, artifact and archive member. The schema alone cannot verify these
relationships; the reader additionally verifies bytes, pointers, package facts
and matching source/component identities for actual-component observations.

The classifications have separate meanings:

| Status | Meaning |
| --- | --- |
| `tested-default-path` | The named finite cases passed in actual signed components using ordinary default construction. It does not qualify every member of the library or another configuration. |
| `supported-ordinary-configuration` | An identified ordinary configuration has compiler or actual-component support evidence. This does not turn it into a tested default path. |
| `optional-adapter-assisted` | The example supplies an optional application adapter. It cannot satisfy default-path requirements. |
| `known-incompatible` | Retained compiler/component evidence identifies a concrete unsupported or blocked condition in the named scope. A package name alone is not a blocker. |
| `untested` | The scope has no execution result. An absent entry has this same meaning; it is never permission denial. |

To add a result, retain bounded public JSON from its original qualification,
record the artifact/member and exact byte identity, and bind each dimension to
those documents. Record the package facts through `packageBindings`; retain
limitations and observed cases. Calculate the entry identity with
`tools.compatibility_catalogue.identity` over the complete entry without its
`identity` field, then run the reader. This calculation is a content key, not an
execution attestation. Review the original execution and claims before publishing.
Do not add credentials, protocol payloads, signing material or private locations.
Changing any scope, claim or document provenance creates a different entry
identity. The entry binds the complete document manifest as well as selected values. Preserve original
receipts and failed/not-run distinctions when adding later observations.

The first entry reuses the original Java HTTP-request execution from run
38859355061/job116837864409, artifact12033094958, source
`160107c857a70f141d2ab74d79fe195d40498ebe`. Actions run, job and artifact
metadata identify that source. The artifact name retains an older `a77af596` label;
its filename is not used as source attribution. The retained documents are byte-exact
public members from that artifact. This is a historical thirteen-case plain HTTP
observation, not a new run or a current-development qualification. In particular,
the compiler's original profile document retains `qualification=pending`; its
separate signed receipt supplies the finite execution result. Neither receipt is
rewritten to make the other appear more qualified.

Version 2 adds the exact Ky 2.2.0, Wretch 3.0.9 and outside private consumer
from the signed TypeScript phase programme at source
`01d913aae212bd3f5dd14550d5b78187c39008bd`,
[run 39459627034/job 118755383589](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39459627034/job/118755383589),
artifact 12282212612. The ten TypeScript documents and six historical Java
documents are byte-exact original artifact members. The npm entries
use the original captured `node_modules/ky` and `node_modules/wretch` locations
as their bound coordinates; the adjacent version and original archive digest
identify the packages. The private entry binds its original name, version and
captured package tree. It does not publish the private source payload.

These entries describe their respective calls within one shared 27-guest,
four-pre-entry-refusal programme, including two-tenant reuse and physical
retirement. They do not assign every shared case to every client. The named
2,000,000,000-fuel profile and finite owner limits remain explicit. Runtime
selection receipts retain their original unknown/not-evaluated qualification;
the separate signed receipt supplies the actual finite result. The catalogue
does not infer a catalogue-absence result, new TLS qualification, native-memory
bound or complete ticket closure from this evidence.

The same edition also adds unchanged Sling v1.4.0 and Requests v0.24.3 from
[Go run 39461611124/job 118762220036](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39461611124/job/118762220036),
source `1ad058275522672ccd566d78ab718c5c6485a176`, artifact 12284315082.
Seven additional byte-exact documents bind the package coordinates, original
artifacts, captured graph, compiler/runtime transformations, WIT and signed
nineteen-case/four-pre-entry-refusal programme. Its single component crosses
two tenants with fifteen real peer contacts and physical/provider retirement.
This is the original v4/6f5 execution; the maintained workflow's later f919
acquisition configuration supplies no new guest execution. Managed-v5 accounting,
HTTPS and production stream/kernel qualification remain separate. Version 2 now
contains six entries backed by twenty-three original public documents.

[Version 3 publication #1245](https://github.com/KirilsTurkins/latent-service-fabric/pull/1245)
preserves those six entries and adds Flurl.Http 4.0.2 and Refit 16.4.0 from the
original source `7ee` twenty-call/two-refusal signed .NET programme. Refit retains
its supported ordinary captured serializer/generator configuration; optional
handler cases supply no default-client credit. The original failed `7e3`
progress writer and runtime-selection unknown/not-run labels remain intact.
This catalogue update supplies no new execution, HTTPS, full-runtime or
native/kernel-accounting qualification.

Reusable API/runtime contracts remain separate from sample package entries:

- [Dependency and API diagnostics](../component-development/library-compatibility.md)
- [Go invocation runtime](../runtime/go-activation.md)
- [Java invocation runtime](../runtime/java-activation-fibers.md)
- [Exact host ABI profiles](../runtime/host-abi-profile.md)
- [Approved outbound stream contract and remaining installation gates](../runtime/outbound-stream-profile.md)

Those documents describe their own implemented/proposed boundaries. A package
entry does not enable scheduling, typed HTTP, raw streams, inbound handlers or an
unavailable standard API. Native reference results do not qualify an emitted
guest. None of these entries proves allocator/kernel bounds, clean-host delivery,
arbitrary middleware retry safety or the complete six-language gate. #694 remains
open for its remaining implementation, tutorials, measurements and qualifications.

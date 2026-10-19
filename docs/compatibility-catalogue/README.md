# Informational compatibility catalogue

The [version 1 catalogue](v1/README.md) and its [JSON data](v1/catalogue.json)
publish finite package observations. The [schema](v1/schema.json) describes their
machine-readable structure. They are optional documentation: dependency capture,
compiler selection, signing, admission and capability grants do not consume them.
An unknown coordinate has the same opportunity to build and execute as a listed
coordinate using the same implemented API/profile and explicit authority.

Read and verify the retained document bytes and entry bindings from a checkout:

```sh
python -m tools.compatibility_catalogue docs/compatibility-catalogue/v1/catalogue.json
python -m tools.compatibility_catalogue docs/compatibility-catalogue/v1/catalogue.json --json
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
Changing any scope or claim creates a different entry identity. Preserve original
receipts and failed/not-run distinctions when adding later observations.

The first entry reuses the original Java HTTP-request execution from run
38859355061/job116837864409, artifact12033094958, source
`a77af5963dbfb158101c68331a016f9541bda2ee`. The retained documents are byte-exact
public members from that artifact. This is a historical thirteen-case plain HTTP
observation, not a new run or a current-development qualification. In particular,
the compiler's original profile document retains `qualification=pending`; its
separate signed receipt supplies the finite execution result. Neither receipt is
rewritten to make the other appear more qualified.

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

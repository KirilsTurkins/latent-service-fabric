# Authenticated private NuGet lifecycle

This programme advances #687's private-feed, captured-original and offline
lifecycle requirements. Source tests and actual NativeAOT/node qualification are
separate evidence. A newly committed programme is not a completed native run.

## Explicit restore trust

`dotnet_capsule.py resolve --feed-config policy.json` accepts the ordinary
`sources` policy plus an optional explicit public CA bundle:

```json
{
  "sources": [{
    "name": "team",
    "url": "https://packages.example.invalid/index.json",
    "patterns": ["Outside.*"],
    "authorizationEnv": "LSF_NUGET_TEAM_PASSWORD",
    "username": "developer"
  }],
  "tlsTrust": {"caFile": "feed-trust/public-roots.pem"}
}
```

The project-relative file contains only parsed public X509 certificates. It is a
complete trust bundle for this restore, including any public roots needed for
the unchanged SDK sources. It cannot contain a private key or an option to
disable certificate or hostname checks. Its exact bytes are captured in the
native lock and checked again during exact review, offline verification and
component compilation. Missing, linked, changed or foreign bundles refuse.

The explicit profile is maintained on Linux. The owned restore child receives
`SSL_CERT_FILE` pointing to a private copy and `SSL_CERT_DIR` pointing to an
owned empty directory. The resolver rechecks both copies and child selections
around restore and before publication. It never installs a root, changes machine
trust or modifies the parent environment. Other platforms refuse this explicit
profile; omitting it preserves the existing restore configuration and defaults.
Credentials remain private native-restore inputs and are absent from captured
source, native graph identities and public diagnostic receipts.

## Maintained qualification

The .NET job runs `qualify_dotnet_private_dependencies.py` after its ordinary
captured NuGet qualification. It rechecks the exact five existing native
products, current .NET source inventory and four unchanged companion builds.
There is no second native/runtime or SDK installation.

The programme compiles two ordinary pure managed outside libraries at two
versions. Runtime-selected package coordinates are absent from the SDK package
catalogue. The main assembly calls its transitive leaf; the leaf reads an
embedded Unicode resource, while the main checks initialization and fresh
per-activation state. An owned HTTPS NuGet v3 peer requires Basic authentication.
Only that peer's public certificate joins the explicitly selected public bundle.
Its private key and random password remain outside the application.

Normal `add`, `resolve`, exact `review-lock`, `dependencies`, `update` and
`remove` commands produce three reviewed source states. Missing/wrong credentials
and an untrusted peer must fail without replacing the accepted lock. Missing or
tampered captured originals and changed CA bytes must refuse before compilation.
An edit invalidates the old native graph until the new exact candidate is reviewed.

The peer is physically closed and joined, its listener refuses connections and
all original library sources/packages/key files are removed before application
compilation. The programme then performs four contained offline NativeAOT builds:
two identical initial builds, the updated graph and the removed graph. The
removed graph contains neither private package and uses the ordinary greeting.
Each of the three states is independently signed, admitted and executed through
the ordinary five-capsule node programme. Additional dynamic calls bind the
intended publication, actual global route snapshot and exact component revision,
then observe idle ownership and clean node shutdown.

Only fixed public JSON summaries, build markers and node receipts are uploaded;
the peer workspace, private key, credential values and raw restore streams are
excluded. Failures stay failures; no retry, warmup, trust bypass, automatic
execution approval, compiler authority or existing job budget is added.

## Remaining boundaries

This is finite pure-ingestion evidence, not an authenticated publisher, clean-host
or hermetic-build claim. Descriptor-selected reflection and unsupported dynamic
or reflection operations require their own actual-component evidence. #687 and
the broader six-language tickets remain open until their literal criteria and
required tests are independently reconciled with successful source-bound runs.

## Fixed-source build variance diagnostic

The explicit `private_nuget_variance` workflow input is a diagnostic for the
retained `03a3f745` private-feed programme, not a replacement normal qualification.
It retrieves only the source-bound five native tools and four companion package
inputs from artifact `12206326792`. Artifact/run/head/size/digest, source-before
and source-after maps, native binary hashes and package inventories must match;
the unchanged `prepared_inputs` consumer checks them again before use.

The separate job installs the ordinary pinned NativeAOT tools, then performs
fresh private capture and offline builds. It does not repeat native application
compilation, the full SDK programme or the printed guide. The exact component
identity assertion remains mandatory. Both initial/rebuilt component and raw
NativeAOT products, observations and input identities are retained for comparison;
private keys, credentials and raw command streams are excluded from this upload.
No deterministic-build cause, private signed lifecycle pass, current development
compilation or whole-ticket completion is implied by this diagnostic.

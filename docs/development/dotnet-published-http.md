# Published .NET HTTP clients

This programme uses unchanged Flurl.Http4.0.2 and Refit16.4.0 through ordinary
`new FlurlClient()` and Refit's `RestService.CreateHttpClient(endpoint, settings)`
followed by `RestService.ForGenerated<IDomainApi>(client, settings)`.
These standard factories retain the default handler and an explicit client
lifetime for NativeAOT. Their ordinary
System.Text.Json metadata and original NuGet generator are captured build
inputs. Neither path injects an LSF handler, scheduler or transport. Two outside
private NuGet consumers use ordinary `HttpClient` and parse actual domain JSON;
their coordinates vary and their original source/feed directories are removed
after normal resolution and exact lock review.

The existing finite default HttpClient profile supplies the underlying BCL and
typed HTTP boundary. It preserves exact origin/method/path grants, protected
provider credentials, activation ownership and original8/2/8/16/8/8/8 runtime
limits. Flurl's own supported status/redirect/cookie behavior remains library
code. Unsupported BCL options or socket APIs retain concrete refusals; the
programme makes no general Microsoft.Extensions.Http factory, SocketsHttpHandler,
CLR host, full socket or arbitrary serializer claim.

The new source gate requires twenty signed library calls and two pre-entry
grant refusals: parsed success through both libraries and both private identities,
404/500 parsing, genuinely held-response cancellation, reserved headers and
uncontacted foreign targets, POST bytes and uncertain mutation without replay,
pre-cancellation, early body disposal, fresh default state and separately labelled
public guest-handler success/denial. Fifteen exact real contacts, eleven completed
writes, one committed mutation and zero final physical/provider owners are
required. An optional guest DelegatingHandler supplies no privileged provider or
extra grant.

Source/capture and staged compiler boundary controls pass. Run39474941546 at
7e3de703bc7666cee9407ff15205b9d5809a9c20 completed normal NuGet resolution,
generator execution, NativeAOT and packaging. The original Flurl and Refit domain
calls both passed before the evidence writer refused to overwrite its progress
file. That failed programme is retained as a failure.

The replay gate authenticates that original archive and component, checks all
captured SDK/build inputs and generator approval, and restores only the five
original WIT files from their authenticated package layers. Its sole original
node change gives each progress record a distinct filename. All twenty signed
cases and two pre-entry refusals remain mandatory. The [owning replay](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39482018386/job/118833387604)
passed all twenty signed cases and both refusals on source
`7ee022fe5305cb86b47d6e08eefaf65aac93e4ae`. Independent review checked the
complete 272-member archive, both source-material sets, all 154 raw CLI records,
22 physical/provider retirement observations, exactly fifteen contacts, eleven
completed writes and one uncertain mutation without replay. Node shutdown is
clean and both node and peer are reaped. The [original raw programme and node
receipts](../testing/evidence/dotnet-published-http-signed-2026-10-20.json) retain
the successful replay separately from the original failed evidence writer.
The original full compiler job remains available through the explicit
`fresh_component` dispatch input. Replay builds neither the guest nor the host.
Existing direct HttpClient results retain their historical scope and source;
they do not give these new libraries passing credit. #693 remains open for the
remaining literal lifecycle, authority, HTTPS and isolation
requirements. No complete ticket or production accounting claim is made here.

The optional [versioned compatibility observations](../compatibility-catalogue/v3/README.md)
bind these two NuGet packages to their original graph, component, configuration,
compiler, runtime and node binary. Dependency resolution and admission remain
independent of the catalogue.

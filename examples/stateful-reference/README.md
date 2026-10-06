# Stateful order-draft reference

One business WIT, schema and Angular UI serve the Rust, C, TypeScript, Go,
Java and C#/.NET guest implementations. The application uses the maintained
transaction/query/intent SDK owners. A source build does not grant namespace,
publication, result lookup or provider authority.

Each draft has two related keys. Both contain the same twelve-byte revision
and units value; absent keys represent revision zero, and partial or mismatched
state is a declared malformed-state error. The explicit screen revision is a
business precondition. Commands retain it without refreshing it after an
uncertain response. A successful edit stages both keys and two deferred intents
in its original transaction. A controlled rejection follows staging so the
host must discard both state writes and both intents while retaining the
original rejection.

The sealed namespace is `order-drafts-<draft-id>`. Every guest checks that
identity before its first read or stage. Separate authenticated draft owners
use distinct namespaces; knowing another draft's ID is not a namespace grant.
The node's current namespace, result-read and effect policies remain required.

Query returns fresh read-only observations. `namespace-view` is the namespace
view, while optional `key-version` comes from the primary key read. Update
returns the original pre-write observations; its changed business revision
does not pretend to be a committed view token. HTTP acknowledgement supplies
the host-owned committed token for the next query.

Create an application outside the checkout through the existing captured SDK
creators:

```sh
python tools/stateful_reference_project.py --language rust --draft-id alice --output ../order-draft-rust
python tools/stateful_reference_project.py --language c --draft-id alice --output ../order-draft-c
python tools/stateful_reference_project.py --language typescript --draft-id alice --output ../order-draft-typescript
python tools/stateful_reference_project.py --language go --draft-id alice --output ../order-draft-go
python tools/stateful_reference_project.py --language java --draft-id alice --output ../order-draft-java
python tools/stateful_reference_project.py --language dotnet --draft-id alice --output ../order-draft-dotnet
```

The captured SDK and original template lock remain unchanged. The ordinary
language build captures the edited application source and binding inputs.
`order-draft-source.json` identifies the selected source/WIT/schema; the
transaction companion declares only strict `edit` and fresh read-only `query`.
Application state allowances narrow to 4 KiB reads, 1 KiB writes and two intents;
the selected language's existing compiler/runtime/watchdog limits remain intact.

The shared browser client uses the existing `transaction-http-v1` routes,
`idempotency-key`, explicit abort-fence retry and minimum-view query headers.
It makes no automatic mutation retry and retains the original request bytes
and identity after response loss. Business rejection remains terminal until
the user explicitly finishes that command. The client preserves all u64 bits,
limits response bytes and request time, refuses foreign origins and clears
private observations when current authority refuses access.

`angular/angular-build.json` uses the maintained `angular-ssr-component-v1`
and `scoped-http-get-v1` profiles. The renderer prepares only the two fixed
fresh-query URLs selected from sealed user/tenant context. Deployment must
install their static loopback address mapping, independent protected read-only
credential references and current caller policies. Each credential is limited
to its single namespace's fresh-query operation; it has no command, result or
effect authority. Neither credential is exposed to Angular or the browser.
The renderer returns no cookie or cache-policy header; shared ingress owns
the final authenticated document, immutable asset and publication behavior.

After the ordinary language package has been signed, admitted and deployed,
`tools/stateful_reference_deployment.py` derives the four purpose-specific
HTTP triggers and two installed state-operation constraints from its exact
transaction companion bytes and actual publication/revision/generation inputs.
The shared trigger schema describes commands, queries and original-result
lookup, retaining both existing buffered and static profiles. These declarations
confer no namespace, result-read or effect grants. Their policy identities,
provider installations and current-user access must be applied independently
through the maintained operator workflow.

`tools/check_stateful_reference.mjs` drives one frontend against the selected
actual node backend. It checks SSR DOM reuse, the captured immutable client
asset, submit/query freshness, stale-edit rejection, original lost-result
recovery, stable-subject token rotation and same-tenant result refusal. Its
response-loss schedule obtains the node's actual terminal response and then
aborts delivery; it creates no substitute browser response. The node conductor
must attest each selected guest's admitted component/compiler/ABI identities
and actual command records before treating the browser receipt as qualification.

Current source checks cover creation of all six captured projects, identical
export contracts, preserved SDK bytes and runtime worlds, pinned canonical
binding generation and nine browser-client unit transport scenarios. The Java
guest has passed the maintained TeaVM/C/closed-runtime component compiler;
Angular has passed its maintained source guard, compiler and bundler. These
checks establish authored source and compiler behavior. Signed admission,
the remaining guest builds, supported live SSR composition, real browser
DOM hydration/recovery, transactional incoming-event handling, restart,
schema/retention/rollout and provider/physical-owner scenarios still require
the exact-source integrated node campaign before #402 can close.

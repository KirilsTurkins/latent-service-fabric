# ADR-0045: Bound larger static documentation inventories

- Status: Accepted
- Context: first integration feedback #630

## Decision

Admit at most 252 public assets per web manifest. Keep the package format's
256-layer ceiling: the maintained capture/assembly path uses two private capture
metadata layers plus the embedded SBOM and build-input receipt. Custom metadata
or an SSR renderer shares that total and can reduce the remaining public count.
Asset paths remain separate entries even if they share immutable content.

Bound the capture input descriptor and web manifest to 256 KiB, matching the
existing package document ceiling. Keep 8 MiB per public asset, 16 MiB per public
tree, 128 explicit routes, finite path/string lengths, and all existing catalog
and serving budgets. This admits the reported 250-file workload without changing
per-file, aggregate-content or package-layer maxima.

Logical count and allocation capacity have separate guards. A JSON-decoded
252-entry Vec can reserve 256 slots; the physical allowance is bounded to 256,
and `CheckedWebLayout::retained_bytes` charges its actual capacity. More than
252 logical entries or 256 allocated slots is rejected before indexing.

## Coupled bounds and ownership

| Surface | Bound and treatment |
| --- | --- |
| Capture | 252 explicitly selected public assets; 256 KiB descriptor; 128 deliberate exclusions; no recursive discovery |
| Web metadata | 256 KiB encoded manifest; 252 entries, at most 256 Vec slots; existing bounded JSON depth, nodes and strings |
| Package | Existing 256 layers, 256 KiB config/manifest, 64 MiB per layer and 256 MiB total package layers; public assets retain stricter 8/16 MiB limits |
| SBOM | Existing 4096-entry and 1 MiB limits; all captured outputs are represented; dependency observations remain incomplete when declared incomplete |
| Builder evidence | Existing 256-output bound; web output identity excludes the SBOM and input receipt and therefore fits the package bound |
| Catalog | Existing global content, metadata, publication and file-count budgets; count expansion does not waive current admission or publication pins |
| Serving | Existing shared bounded read/output/cache owners; lookup walks a finite admitted inventory and creates no per-site worker |

Count and byte errors report a named bound and numeric actual/maximum values;
they do not include operator paths or content. Limits still intersect: a smaller
node budget can reject an otherwise structurally valid package.

## Verification

Capture and native-layout tests admit exactly 252 long-path entries with a web
manifest larger than the old 64 KiB ceiling, reject 253 entries with an exact
diagnostic, and retain existing duplicate/path/media/content rejection tests.
The maintained generator emits a complete 250-file English/German tree. The
existing real-node workflow packages, signs, distributes, publishes and serves
it; the browser checks both locales under root and mounted routes. Its existing
ownership assertions still require zero guest activations and drained resources.

This fixture qualifies the bounded static inventory, not every Docusaurus plugin
or an Azure host. Framework/CSP qualification remains #629; managed-host storage
and process ownership have their own tickets.

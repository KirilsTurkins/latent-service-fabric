# Separate-filesystem CLI/RPC proof

The unchanged [receipt log](issue15-namespace-proof.log) records one successful
echo activation after component publication and deployment through actual RPCs
between a caller and node in distinct mount namespaces. The exact
[proof script](issue15-namespace-proof.py) is retained for methodology review.
It contains the original environment-specific Docker workflow; retaining it
does not execute or adapt that workflow.

The [file manifest](files.manifest.json) binds the original 16,719-byte script and
6,526-byte log. The log is UTF-16LE with its original BOM, as captured on the
collection host; it has not been converted to UTF-8. Package-local attributes
prevent Git line-ending conversion, and the ignore override retains the log.

| Observation | Recorded result |
| --- | --- |
| Client / node mount namespaces | `4026532293` / `4026533068`, distinct |
| Caller directories mounted into node | None; recorded node mount list is empty |
| Unique caller package path present inside node | False before publication and after invocation |
| Publication / deployment | Component bytes sent over RPC; deployment generation `1` |
| Invocation | One attempt, `success`, activation `namespace-proof-invoke` |
| Retained terminal state | `completed`, with the same revision pin and final accounting |
| Complete proof duration | 25.569 seconds, including setup/inspection/cleanup |
| Shutdown | Clean; zero transient owners; telemetry flushed; epoch helper joined |
| Cleanup | No failures; original persistent container left untouched |

This proves the caller/node filesystem boundary for the recorded workflow.
Deleting caller files only after publication would be a weaker observation.
The receipt includes actual CLI/node/component/capsule/contracts byte hashes,
the image identity, configuration hash, namespace observations, response pin,
consumption and complete shutdown fields. It records the following input
identities:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| `latent` debug executable | 102,826,776 | `755d89e16a1402e624019e65437f4abba1d1aeb307f5638670cac255202a671d` |
| `latentd` debug executable | 380,676,136 | `6ec52e8c11574359d27a16c29d5a34d154f2491ac448976ab4f2a98ebb08e173` |
| Echo component | 24,754 | `a45c2680dcbb6f5a67c532459cc2ff14daaa5b893f793b92eecec31c7488a694` |
| Capsule JSON | 1,392 | `f36ade6ae9c716960475be95588d2ca8c4cea7ed4f33d3988873e0b6d419129a` |
| Contracts JSON | 1,349 | `8e2d862da2819d6a5a43266af2c8e79eb8f98e16f4492ae325f2a995081b003e` |

No source commit/tree or clean-checkout assertion is added: the original receipt
does not record one. The input bytes are identified by its original hashes;
those executable files are not included in this small receipt package. This
one-call debug-binary proof is separate from CI conformance and the release-built
full scale/soak/benchmark suite. It is not calibration evidence or a general
network isolation claim.

Retention checked both files byte for byte and verified the three JSON events,
distinct namespace identities, absent caller path, one successful invocation,
terminal state, zero transient shutdown counters and successful cleanup. The
script was not rerun. To inspect the exact recorded JSON without invoking it:

```sh
python3 - <<'PY'
import json
from pathlib import Path
path = Path('benchmarks/phase1/conformance/2026-09-08-namespace-proof/issue15-namespace-proof.log')
for line in path.read_text(encoding='utf-16').splitlines():
    print(json.dumps(json.loads(line), indent=2, sort_keys=True))
PY
```

See the [completion review](../../../../docs/phase-1-completion.md) for the
remaining gate decision and the separate measurement evidence.

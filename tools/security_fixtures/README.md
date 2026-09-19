# Harmless security canaries

These files are scanner data, not runtime dependencies or executable test payloads.
Do not rename the lock fixtures to a workspace `Cargo.lock`, add them to Cargo
members, install their packages or publish native secret reports.

| Fixture or generated input | Expected result |
| --- | --- |
| `clean.lock.fixture` | No RustSec match for the non-published fixture package |
| `vulnerable.lock.fixture` | The reviewed `time` 0.1.44 entry produces `RUSTSEC-2020-0071`; no crate is downloaded or executed |
| `expired-exception.json` | Exception validation rejects the entry on the fixed test date |
| Generated Markdown/SVG | Harmless text passes; the synthetic marker fails even with an inline allow comment |
| Generated source/workflow | Constant assignment and inert echo pass; lexical dynamic-execution and workflow-expression injection examples fail without execution |
| Unavailable database at loopback port 1 | Real Git failure is reported, never an empty audit success |
| Mocked stale/head-mismatched DB, stale/truncated/unknown OSV data | Required data validation fails |
| Malformed tool archive/digests, linked input, oversized output, timed-out child | Installation/input/process validation fails |
| Fork PR and unchanged-lock schedule events | Read-only/no-secret/no-cache workflow policy holds; both maintained refs select scans without consulting a changed lock |
| Missing/unknown manifest or partial legacy feature directory | Inventory fails; an entirely unshipped optional feature is explicitly recorded, while scanner-control dependencies are always checked |
| Docs/SVG and aggregate fixtures | Docs keep the existing cheap CI profile; failures, cancellation and unexpected skips cannot pass the security aggregate |

Run from the repository root with reviewed scanners installed as described in the
[operator runbook](../../docs/development/security-baseline.md):

```powershell
python -m unittest discover -s tools/tests -p 'test_security*.py'
python tools/security_selftest.py --tools target/security-tools --scratch target/security-canaries
```

The self-test exits successfully only when clean inputs pass **and** expected bad
inputs are detected. Its eight named categories use actual pinned scanners and a
fresh verified RustSec database. It generates the non-credential marker only in
temporary storage and removes that storage afterwards. Unit fixtures separately
test data/permission/expiry failure contracts; they do not exercise GitHub's
server push protection or execute a real fork PR. On Windows, symlink construction
may be unavailable and is explicitly skipped; Linux CI must run that test.

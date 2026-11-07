from pathlib import Path
import json, yaml
root = Path.cwd()
old = 'c=crates/latent-component-threading/src/rust_catalogue'
new = old + '/combined-corrected-v1'
old_sha = '5634429a97b4a3f0cf8afca2877dbbddbc98f5e4fd7bf59ae6f7f50e780c2e17'
new_sha = 'ab7c8e29be5745ff29fa5788ab13f3cc2bdde87da5033e41e9f804dcb3d83032'
p = root / '.github/workflows/rust-combined-host-diagnostic.yml'
s = p.read_text(); assert s.count(old) == 1 and s.count(old_sha) == 1
p.write_text(s.replace(old, new).replace(old_sha, new_sha))
p = root / '.github/workflows/rust-combined-signed-witness.yml'
s = p.read_text().replace('Retrieve only the pinned original compiler members', 'Retrieve only the pinned corrected compiler members').replace('rust-combined-original', 'rust-combined-compiler')
p.write_text(s)
p = root / '.github/workflows/rust-wasi-http-runtime.yml'
s = p.read_text()
needle = '      - name: Acquire only locked SDK compiler sources before offline compilation\n'
assert s.count(needle) == 1
s = s.replace(needle, '''      - name: Verify completed EOF retirement and pending cancellation ownership
        shell: bash
        run: |
          set -euo pipefail
          rustc --edition=2021 -D warnings --test sdk/wasi-http-runtime/retirement.rs -o "$RUNNER_TEMP/rust-http-retirement-controls"
          "$RUNNER_TEMP/rust-http-retirement-controls" --test-threads=1 | tee "$RUNNER_TEMP/rust-http-retirement-controls.txt"
''' + needle)
needle = '          cargo --config .cargo/managed-guest.toml --config profile.dev.opt-level=1 run --locked --offline -p latent-toolchain-smoke --example rust-http-pump-control -- "$RUNNER_TEMP/rust-http-pump-probe.wasm" 2>&1 | tee "$RUNNER_TEMP/rust-http-pump-guest.txt"'
assert s.count(needle) == 1
s = s.replace(needle, needle + '\n' + needle.replace('"$RUNNER_TEMP/rust-http-pump-probe.wasm" 2>&1', '"$RUNNER_TEMP/rust-http-pump-probe.wasm" --native-profile 2>&1').replace('rust-http-pump-guest.txt', 'rust-http-pump-native-guest.txt'))
s = s.replace('            ${{ runner.temp }}/rust-http-pump-guest.txt', '            ${{ runner.temp }}/rust-http-retirement-controls.txt\n            ${{ runner.temp }}/rust-http-pump-native-guest.txt\n            ${{ runner.temp }}/rust-http-pump-guest.txt')
p.write_text(s)
for workflow, job in [('rust-combined-host-diagnostic.yml', 'diagnostic'), ('rust-combined-signed-witness.yml', 'signed-witness'), ('rust-wasi-http-runtime.yml', 'standard-backend')]:
    definition = yaml.safe_load((root / '.github/workflows' / workflow).read_text())['jobs'][job]
    for step in definition['steps']:
        if 'uses' in step: step['uses'] = step['uses'].split('@')[0]
    p = root / 'tools/ci/contracts/workflows' / workflow / 'jobs' / (job + '.json')
    value = json.loads(p.read_bytes()); value['definition'] = definition
    value['reviewReason'] = 'Bind the corrected source-captured graph and retain ordinary refusal, independent grants, finite ownership, compiled sequential progress, physical retirement and original signed witness gates.'
    p.write_text(json.dumps(value, indent=2) + '\n')
p = root / 'sdk/wasi-http-runtime/README.md'
s = p.read_text().replace('| [poll.rs](poll.rs) | Pollable readiness and timers using the shared activation pump. |', '| [poll.rs](poll.rs), [pump.rs](pump.rs), [timer.rs](timer.rs) | Callback-safe readiness, bounded waiters and original timer futures. |\n| [retirement.rs](retirement.rs) | Physical resource and buffer destruction before owner settlement, including EOF and deferred cancellation. |')
a = s.index('The adapter reuses'); b = s.index('\n## Producer and consumer identities', a)
s = s[:a] + '''The adapter reuses the original .NET HTTP runtime's
[Owner](../dotnet-guest/runtime/http/owner.rs) and
[quota](../dotnet-guest/runtime/http/quota.rs) sources. Rust's separate
[pump](pump.rs) returns pending from async exports instead of blocking an
entered component instance; its [timer](timer.rs) retains the original accepted
clock future. The .NET pump and timer are unchanged. These guest scheduling
changes add no provider, budget, socket authority or connection cache.

Futures, resources and buffers retain their original owners through actual
retirement. Dropping an exchange with observed EOF, no pending canonical future
and no upload destroys its body and buffered data before settling its Task.
Completed sequential requests therefore do not consume Task capacity until an
unrelated held request permits root cleanup. Pending cancellation still retains
the same future, resources, buffers, owner and quota slot until async-root drain;
logical cancellation never proves physical work stopped. Native retirement and
actual compiled sequential-sibling controls are maintained in
[the backend workflow](../../.github/workflows/rust-wasi-http-runtime.yml).
''' + s[b:]
p.write_text(s)
p = root / 'docs/testing/rust-combined-http-diagnostic.md'
s = p.read_text().replace('Rust HTTP/ThreadPool component. It does not enable', 'Rust HTTP/ThreadPool component. The selected image is the separate\n`rust_catalogue/combined-corrected-v1` set, not the historical failed image.\nIt does not enable')
a = s.index('original compiler artifact.'); b = s.index('\nThe controller builds with', a)
s = s[:a] + '''corrected compiler artifact. `origin.json` binds its run, compiler job, source
commit/tree, recipe, capture, raw core, composition and framed component.
Compiler job `128393351609` in run `42369110799` successfully compiled the
corrected fixture, callback-safe pump and completed-EOF retirement from commit
`1d81c35ca6b206bafba113b6214de09bc6781bdb`. Both that job and its workflow
passed. Its 251 recipe inputs match the recorded source. Packaging checks the
original successful compile/composition commands and exact public surface; it
does not recompile the application or rewrite its compiler receipt.

The pinned archive is 67,919,611 bytes with SHA-256
`ba5b77a22012f22f503839470858383c6847783b7b04abd3614bf680d8c92210`.
Its 209 members passed independent CRC and whole-archive digest inspection.
The maintained retriever obtains only nine fixed, size- and hash-pinned members
and records that its archive digest check uses official metadata, not a claim
that the retriever downloaded the entire archive again. Expired or changed
artifacts fail; no other compiler run, attempt, graph or source is substituted.

The raw core is 999,654 bytes (SHA-256
`25ecfa4024c125f3c8829216c8c5211097d9f27a8ae86e8385ecfb6526ebfcca`).
The final graph is 1,306,998 bytes (SHA-256
`71e0d0bd5cd4be0578eff4ad0ee02dc0d40f3146bc5e373193f3cbc9b8d3fcef`),
and its frame is 1,654,366 bytes (SHA-256
`ab7c8e29be5745ff29fa5788ab13f3cc2bdde87da5033e41e9f804dcb3d83032`).
These identities grant no authority: the host still independently reconstructs
the transformed core against the unchanged original object catalogue and
checks the entire final graph before admitting its execution context.

The historical catalogue and failed compiler event `41926247914` are unchanged.
The active selector rejects the historical framed image; its accepted set is
replaced, not widened. Earlier callback, Golem-read and three-request deadline
failures remain failed observations. In particular, compiler run `42364782237`
had a successful compiler job but a failed ancillary source-check job; its
signed observation `42366341977` reached three requests before deadline.
Neither is relabelled by the separately compiled EOF-retirement correction.

A successful compiler, source verifier or native regression is not signed
execution qualification. The final host must still pass all requirements below.
''' + s[b:]
s = s.replace('packages and signs the retained component', 'packages and signs the corrected retained component')
p.write_text(s)
p = root / 'docs/testing/rust-http-callback-pump.md'
s = p.read_text()
a = s.index('This changes the developer fixture source'); b = s.index('\n', s.index('head, with independently checked source/build/component lineage.', a))
s = s[:a] + '''The corrected fixture and adapter were compiled together from `27164664` by
compiler job `128380436039` in run `42364782237`. That job completed source
capture, isolated application compilation, composition and interface checks;
its ancillary source-check job failed on an invalid validator command, so that
whole workflow remains failed. Signed observation `42366341977` passed the old
panic and reached a third request, but timed out before the fourth. A bounded
numeric host trace (`42367791040`) observed the third response's body and EOF
within about 27 ms. These are failed observations, not signed qualification.

The subsequent completed-EOF retirement change below was independently built
from commit `1d81c35ca6b206bafba113b6214de09bc6781bdb` in successful compiler
run `42369110799`. The selected `combined-corrected-v1` graph and its original
source/build lineage are described in the [diagnostic guide](rust-combined-http-diagnostic.md).
Old compiler bytes and failed signed results remain intact; successful source
compilation and unit controls cannot substitute for a passing signed witness.
''' + s[b:]
s += '''
## Completed exchange ownership

Completed HTTP exchanges were retaining Task owners until root drain. In a
held-header programme, this unnecessarily retains capacity needed by a later
sequential request even though the previous body has reached EOF.

The Rust-specific retirement frame owns the original canonical future, upload,
body, buffers, activation owner and quota slot in physical-drop order. Observed
EOF is necessary but insufficient: synchronous retirement also requires no
pending future and no upload. Resources and buffered data are destroyed before
the original Task is settled. All other cases remain on the explicit async-root
retirement queue, without early refund, replacement owner, dial retry or replay.
An unwinding resource destructor still retains the owner while the remaining
buffers are destroyed. The .NET implementation is unchanged.

Maintained native controls exercise completed EOF, repeated admission under
finite capacity, retained pending work and destructor unwind. The compiled guest
control separately completes two sequential siblings while the original import
stays held, checks synchronous readiness and deferred cancellation, and requires
empty engine state under ordinary and native-enabled configurations. Neither
control is an authenticated signed-node qualification.
'''
p.write_text(s)

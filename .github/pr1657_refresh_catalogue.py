"""Prepare a separate, exact corrected catalogue from authenticated compiler bytes."""
from pathlib import Path
import os, sys, json, hashlib, zipfile, stat, subprocess
ROOT = Path.cwd()
TEMP = Path(os.environ['RUNNER_TEMP'])
sys.path.insert(0, str(ROOT))
from tools import rust_original_delta as delta, rust_combined_diagnostic_envelope as envelope
ARCHIVE = TEMP / 'pr1657-fresh-compiler.zip'
assert ARCHIVE.stat().st_size == 67901817
assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == '8c8c44d5733e5bdb82e5b9b67eedd1737c09edbc16d104dc55e3cd83334b366f'
source = TEMP / 'pr1657-compiler'
source.mkdir()
selected = ('application-source-and-capture.tar.gz', 'source-inputs.json', 'raw-core.wasm', 'preview-component.wasm', 'combined-component.wasm', 'observation.json', 'rust-http-composition.json', 'recipe-origin.json', 'recipe-inputs.json', 'rust-http-runtime.json')
with zipfile.ZipFile(ARCHIVE) as archive:
    assert len(archive.infolist()) == 203 and archive.testzip() is None
    assert len({x.filename.casefold() for x in archive.infolist()}) == 203
    for name in selected:
        member = archive.getinfo('rust-http-thread-combined/' + name)
        assert not member.is_dir() and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG)
        assert member.file_size <= 32 * 1024 * 1024
        (source / name).write_bytes(archive.read(member))
recipe = json.loads((source / 'recipe-origin.json').read_bytes())
assert recipe['head'] == '27164664b222bc52c88371a2225d147b3f8c020e' and recipe['tree'] == 'b45308aa4be494c749244d017d5cb43afb64c61f'
for row in recipe['files']:
    data = (ROOT / row['path']).read_bytes()
    assert len(data) == row['size'] and 'sha256:' + hashlib.sha256(data).hexdigest() == row['digest'], row['path']
root = ROOT
out = root / 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1'
out.mkdir()
D = lambda b: 'sha256:' + hashlib.sha256(b).hexdigest()
I = lambda b: {'bytes': len(b), 'sha256': D(b)}
def sections(raw):
    p = 8
    result = []
    while p < len(raw):
        start = p
        kind = raw[p]
        length, p = envelope.read_u32(raw, p + 1)
        end = p + length
        assert end <= len(raw) and len(result) < 512
        result.append((kind, raw[p:end], raw[start:end]))
        p = end
    assert p == len(raw)
    return result
def name(payload):
    n, p = envelope.read_u32(payload, 0)
    return payload[p:p+n]
original = (source / 'raw-core.wasm').read_bytes()
preview = (source / 'preview-component.wasm').read_bytes()
final = (source / 'combined-component.wasm').read_bytes()
assert I(original) == {'bytes': 999654, 'sha256': 'sha256:e26658d86f549fc9a29d88d703842acffaee04ed6c986f6d45882d972f1413ee'}
assert I(final) == {'bytes': 1303953, 'sha256': 'sha256:93afb8712d2d3d624f470767f8944e32f29f6a50e5c59bba86cf2439f7946f28'}
rows = sections(preview)
main_index = next(i for i, (kind, _, _) in enumerate(rows) if kind == 1)
main = rows[main_index][1]
assert final.count(main) == 1 and len(main) == 918807
start = final.index(main)
wit = [payload for kind, payload, _ in sections(original) if kind == 0 and name(payload).startswith(b'component-type')]
assert len(wit) == 5
original_producers, = [p for k, p, _ in sections(original) if k == 0 and name(p) == b'producers']
encoded_producers, = [p for k, p, _ in sections(main) if k == 0 and name(p) == b'producers']
assets = {
    'combined-original-core.wasm': original,
    'combined-preview-component.wasm': preview,
    'combined-preview-shell.bin': preview[:8] + b''.join(b'\x01\x00' if i == main_index else whole for i, (_, _, whole) in enumerate(rows)),
    'combined-final-component.wasm': final,
    'combined-final-prefix.bin': final[:start],
    'combined-final-suffix.bin': final[start+len(main):],
    'combined-original-producers.bin': original_producers,
    'combined-encoded-producers.bin': encoded_producers,
    **{f'combined-wit-{i}.bin': payload for i, payload in enumerate(wit)},
    'combined-original-delta.bin': delta.encode(original, final),
}
wrapped = envelope.frame(final, assets['combined-original-delta.bin'])
assert I(wrapped) == {'bytes': 1652323, 'sha256': 'sha256:7e4952870f2ffe337978c0db1c9127e3d891130f7dd26659e928c6020ef829b6'}
for key, data in assets.items():
    (out / key).write_bytes(data)
files = tuple(name for name in selected if name != 'preview-component.wasm')
origin = {
    'schemaVersion': 'latent.rust.combined-fixed-graph-origin.v2',
    'scope': 'fixed corrected diagnostic graph; no execution authority or signed qualification from generation',
    'sourceCommit': '27164664b222bc52c88371a2225d147b3f8c020e',
    'sourceTree': 'b45308aa4be494c749244d017d5cb43afb64c61f',
    'workflowSource': 'b8a028e8778198e27b343297e598542ad9b0c046',
    'workflowPath': '.github/workflows/pr1657-fresh-source.yml',
    'workflowBranch': 'diag/pr1657-fresh-source-20261107',
    'run': 42364782237, 'job': 128380436039, 'jobName': 'compiler', 'artifact': 13570829656,
    'producerJobConclusion': 'success', 'workflowConclusion': 'failure',
    'workflowFailureOutsideCompilerJob': 'source job used a nonexistent ci_contracts.py validate subcommand after all 39 controls passed; maintained validation passed separately',
    'archive': {'id': 13570829656, 'size_in_bytes': 67901817, 'digest': 'sha256:8c8c44d5733e5bdb82e5b9b67eedd1737c09edbc16d104dc55e3cd83334b366f'},
    'artifactName': 'pr1657-fresh-compiler-27164664', 'archiveMembers': 203,
    'compilerObservationStatus': 'observed-composed-http-thread-source-runtime-unqualified',
    'catalogueBodySha256': 'sha256:eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b',
    'finalMainOffset': start, 'finalMainBytes': len(main),
    'compilerMembers': {k: I((source / k).read_bytes()) for k in files},
    'files': {k: I(v) for k, v in sorted(assets.items())}, 'wrapped': I(wrapped),
    'historicalCompiler': {'sourceCommit': '7f1a95ef7f2552bb6b0339e3331cf6b25d765127', 'run': 41926247914, 'artifact': 13371474344, 'outcome': 'failure', 'reclassified': False},
    'applicationRecompiled': True, 'normalRustBuilderRouteOpened': False, 'runtimeQualified': False,
}
(out / 'origin.json').write_text(json.dumps(origin, indent=2) + '\n')
paths = ['crates/latent-component-threading/src/rust_component.rs', 'crates/latent-component-threading/src/rust_original_delta.rs', 'crates/latent-packaging/src/semantics/wasm/tests.rs', 'crates/latent-wasmtime/src/component_threading.rs']
for path in paths:
    p = root / path
    text = p.read_text()
    new = text.replace('rust_catalogue/combined-', 'rust_catalogue/combined-corrected-v1/combined-')
    if path.endswith('rust_component.rs'):
        assert 'const COMBINED_MAIN_BYTES: usize = 920_667;' in new
        new = new.replace('const COMBINED_MAIN_BYTES: usize = 920_667;', 'const COMBINED_MAIN_BYTES: usize = 918_807;')
    assert new != text
    p.write_text(new)
print('Fresh fixed graph extracted and complete compiler recipe matched; independent Rust proof still required.')

"""Ordinary captured Rust thread errors, terminal traps and fresh activations."""
from __future__ import annotations

from pathlib import Path
import shutil

from tools import application_dependencies as dependencies
from tools import cargo_native_authoring as authoring
from tools import rust_application_dependencies as native
from tools import rust_dependency_authoring as review
from tools.build_snapshot import canonical, digest
from tools.phase2_operator_process import require
from tools.rust_capsule_node import assert_value, call, provider_idle, sample, selected_revision
from tools.rust_dependency_recovery import failed
from tools.rust_dependency_fixture import direct_libraries
from tools.rust_capsule_project import snapshot

PACKAGE = 'outside-compatibility-library'
CALLBACK = 'outside-compatibility-callback'
VERSION = '0.3.7'
LIBRARY = r'''use std::sync::atomic::{AtomicU32, Ordering};
static CALLS: AtomicU32 = AtomicU32::new(0);
pub fn describe(mode: &str) -> String {
    assert_eq!(CALLS.fetch_add(1, Ordering::SeqCst), 0, "activation state was reused");
    match mode {
        "caught" => match std::thread::Builder::new().spawn(outside_compatibility_callback::value) {
            Err(error) if error.kind() == std::io::ErrorKind::Unsupported => "unsupported-thread".into(),
            Err(_) => "unexpected-thread-error".into(),
            Ok(thread) => format!("spawned:{}", thread.join().unwrap()),
        },
        "uncaught" => format!("spawned:{}", std::thread::spawn(outside_compatibility_callback::value).join().unwrap()),
        "eliminated" => {
            #[cfg(not(target_arch = "wasm32"))]
            { return format!("native-thread:{}", std::thread::spawn(outside_compatibility_callback::value).join().unwrap()); }
            #[cfg(target_arch = "wasm32")]
            { "eliminated".into() }
        },
        _ => "unknown-probe".into(),
    }
}
'''
CALLBACK_SOURCE = 'pub fn value() -> u32 { 7 }\n'
CASES = (('caught', 'unsupported-thread'), ('eliminated', 'eliminated'),
         ('uncaught', None), ('caught', 'unsupported-thread'))


def install(project: Path, outside: Path, cargo: Path) -> dict:
    """Use normal local dependency declarations, capture and explicit lock review."""
    before = snapshot(project)
    outside.mkdir(mode=0o700)
    library, callback = outside / PACKAGE, outside / CALLBACK
    for path in (library, callback):
        (path / 'src').mkdir(parents=True)
    (callback / 'Cargo.toml').write_text(f'[package]\nname = "{CALLBACK}"\nversion = "{VERSION}"\n'
                                        'edition = "2021"\nlicense = "Apache-2.0"\n', encoding='utf-8')
    (callback / 'src/lib.rs').write_text(CALLBACK_SOURCE, encoding='utf-8')
    (library / 'Cargo.toml').write_text(f'[package]\nname = "{PACKAGE}"\nversion = "{VERSION}"\n'
        'edition = "2021"\nlicense = "Apache-2.0"\n[dependencies]\n'
        f'{CALLBACK} = {{path = "../{CALLBACK}"}}\n', encoding='utf-8')
    (library / 'src/lib.rs').write_text(LIBRARY, encoding='utf-8')
    hook = b'Ok(format!("Hello, {name}!"))'
    require(before['src/lib.rs'].count(hook) == 1, 'compatibility-probe-original-greeting-required')
    source = before['src/lib.rs'].replace(hook,
        b'if let Some(mode) = name.strip_prefix("compatibility:") {\n'
        b'        return Ok(outside_compatibility_library::describe(mode));\n    }\n    ' + hook)
    (project / 'src/lib.rs').write_bytes(source)
    authoring.author(project, 'add', identity=PACKAGE, version=VERSION, local=library, cargo=cargo)
    candidate = outside / 'candidate.json'
    lock = native.resolve(project, candidate, cargo=cargo)
    require(not lock['executableInputs'], 'compatibility-probe-unexpected-executable-input')
    selected, artifacts = {}, {}
    for name in (PACKAGE, CALLBACK):
        rows = [row for row in lock['artifacts'] if row['role'] == 'application'
                and row.get('metadata', {}).get('package') == name and row['metadata'].get('version') == VERSION]
        require(len(rows) == 1, 'compatibility-probe-captured-library-required')
        artifacts[name] = rows[0]
        selected[name] = {'artifact': rows[0]['id'], 'treeDigest': rows[0]['treeDigest']}
    require(selected[CALLBACK]['artifact'] in artifacts[PACKAGE]['dependencies'],
            'compatibility-probe-transitive-callback-required')
    import json
    graph = json.loads((project / 'cargo-resolved.lock.json').read_bytes())
    direct_libraries(graph, lock['artifacts'], {(PACKAGE, VERSION): 'std::thread::Builder::spawn and std::thread::spawn'})
    raw = candidate.read_bytes()
    review.review(project, candidate, digest(raw))
    require(review.status(project)['status'] == 'verified'
            and (project / dependencies.LOCK).read_bytes() == raw,
            'compatibility-probe-reviewed-candidate-required')
    require((project / 'sdk-lock.json').read_bytes() == before['sdk-lock.json'],
            'compatibility-probe-sdk-lock-changed')
    for path in (library, callback):
        require(path.resolve(strict=True).parent == outside.resolve(strict=True),
                'compatibility-probe-cleanup-owner')
        shutil.rmtree(path)
    return {'formatVersion': 1, 'package': PACKAGE, 'version': VERSION, 'libraries': selected,
            'sourceDigest': digest(source), 'librarySourceDigest': digest(LIBRARY.encode()),
            'callbackSourceDigest': digest(CALLBACK_SOURCE.encode()), 'candidateDigest': digest(raw),
            'sdkLockDigest': digest(before['sdk-lock.json']), 'catalogueRegistration': False,
            'originalOutsideSources': 'removed-after-review', 'executableInputs': []}


def probe(client, target, ownership_probe, result, population):
    """Observe exact values and a terminal failure; never continue a trapped call."""
    observations = []
    expected_revision = selected_revision(client, target)
    for index, (mode, expected) in enumerate(CASES):
        row = call(client, target, 'greeting', 'greet', ['compatibility:' + mode],
                   'rust-compatibility-' + str(index))
        result['invocations'].append(row)
        if expected is None:
            failed(row, 'guest-trap', target['budget']['memoryBytes'])
        else:
            assert_value(client, row, [{'ok': expected}])
            require(row['processReaped'], 'compatibility-probe-client-not-reaped')
        revision = row['response']['data'].get('resolvedRevision')
        require(revision == expected_revision,
                'compatibility-probe-selected-revision-mismatch')
        require(int(row['response']['data']['consumption']['outboundRequests']) == 0,
                'compatibility-probe-unexpected-outbound')
        result['samples'].append(sample(client, ownership_probe, 'rust-compatibility-' + str(index), population))
        result['providerIdle'].append(provider_idle(client))
        observations.append({'case': mode, 'invocation': row['activation'],
                             'outcome': 'terminal-trap' if expected is None else expected})
    result['rustCompatibility'] = {'status': 'passed', 'cases': observations,
        'scope': 'ordinary captured Builder error and explicit fallback, cfg-eliminated branch, uncaught trap and fresh invocation',
        'trapCause': 'not-inferred-from-generic-node-error', 'retrySafety': 'unknown'}

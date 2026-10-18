"""Ordinary Git crate calls and immutable outside-project resources for qualification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tomllib
from urllib.parse import parse_qs, urlsplit

from tools import application_dependencies as dependencies
from tools import cargo_native_authoring as authoring
from tools import rust_application_dependencies as native
from tools import rust_dependency_authoring as review
from tools.build_snapshot import canonical, digest
from tools.qualify_rust_git_dependencies import PACKAGE, REPOSITORY, REVISIONS, require
from tools.rust_capsule_project import snapshot
from tools.rust_dependency_fixture import direct_libraries
from tools.rust_capsule_node import assert_value, call, sample

LOCAL_PACKAGE = 'outside-git-component-library'
LOCAL_VERSION = '0.7.2'
LIBRARY = r'''use unicode_xid::UnicodeXID;
pub fn prefix() -> &'static str {
    assert!(UnicodeXID::is_xid_start('A'));
    assert!(UnicodeXID::is_xid_start('\u{03a9}'));
    assert!(!UnicodeXID::is_xid_start('9'));
    assert!(UnicodeXID::is_xid_continue('\u{0301}'));
    assert_eq!(include_bytes!("binary.dat"), &[0_u8, 255, 65, 128]);
    assert_eq!(include_str!("utf8.txt").as_bytes(), &[71_u8, 114, 195, 188, 195, 159, 101]);
    include_str!("greeting.txt")
}
pub fn describe(text: &str) -> String {
    let start = text.chars().filter(|value| UnicodeXID::is_xid_start(*value)).count();
    let continuing = text.chars().filter(|value| UnicodeXID::is_xid_continue(*value)).count();
    let bytes = include_bytes!("binary.dat").iter().map(|byte| format!("{byte:02x}")).collect::<String>();
    format!("{}|start={start}|continue={continuing}|utf8={}|bytes={bytes}",
            include_str!("proof.txt"), include_str!("utf8.txt"))
}
'''
PROBE_CASES = (('A\u03a99\u0301', 'Git source resources|start=2|continue=4|utf8=Gr\u00fc\u00dfe|bytes=00ff4180'),
               ('9_', 'Git source resources|start=0|continue=2|utf8=Gr\u00fc\u00dfe|bytes=00ff4180'),
               ('A\u03a99\u0301', 'Git source resources|start=2|continue=4|utf8=Gr\u00fc\u00dfe|bytes=00ff4180'))


def probe(client, target, ownership_probe, result, population):
    """Three additional ordinary signed calls, including a fresh warm repeat."""
    cases = []
    for index, (value, expected) in enumerate(PROBE_CASES):
        row = call(client, target, 'greeting', 'greet', ['git-proof:' + value], f'authoring-git-proof-{index}')
        result['invocations'].append(row)
        assert_value(client, row, [{'ok': expected}])
        result['samples'].append(sample(client, ownership_probe, f'after-git-proof-{index}', population))
        cases.append({'inputDigest': digest(value.encode()), 'expected': expected})
    result['capturedGitComponent'] = {'status': 'passed', 'cases': cases,
                                      'scope': 'dynamic ordinary UnicodeXID APIs and captured immutable resources'}


def selected(lock: dict, graph: dict) -> dict:
    version, revision = REVISIONS[-1]
    matches = [row for row in lock['artifacts'] if row['role'] == 'application'
               and row['metadata'].get('package') == PACKAGE and row['metadata'].get('version') == version]
    require(len(matches) == 1, 'Git-component-captured-package-mismatch')
    artifact = matches[0]
    nodes = [row for row in graph['nodes'] if row.get('artifact') == artifact['id']]
    require(len(nodes) == 1, 'Git-component-source-identity-missing')
    source = nodes[0].get('source', '')
    require(isinstance(source, str) and source.startswith('git+'), 'Git-component-source-not-Git')
    parsed = urlsplit(source[4:])
    require(parsed.fragment == revision and parse_qs(parsed.query, strict_parsing=True) == {'rev': [revision]}
            and authoring.git_url(parsed._replace(query='', fragment='').geturl()) == authoring.git_url(REPOSITORY)
            and artifact['metadata']['nativeSourceDigest'] == digest(source.encode()),
            'Git-component-source-revision-mismatch')
    require(not lock['executableInputs'], 'Git-component-unexpected-executable-input')
    return artifact


def install(project: Path, outside: Path, cargo: Path) -> dict:
    version, revision = REVISIONS[-1]
    initial = snapshot(project)
    require(not any(row['name'] == PACKAGE for row in tomllib.loads(initial['Cargo.lock'].decode())['package']),
            'Git-component-package-already-in-SDK-lock')
    outside.mkdir(mode=0o700)
    library = outside / LOCAL_PACKAGE
    (library / 'src').mkdir(parents=True)
    (library / 'Cargo.toml').write_text(f'''[package]
name = "{LOCAL_PACKAGE}"
version = "{LOCAL_VERSION}"
edition = "2021"
license = "Apache-2.0"
[dependencies]
{PACKAGE} = {{git = "{REPOSITORY}", rev = "{revision}"}}
''', encoding='utf-8')
    (library / 'src/lib.rs').write_text(LIBRARY, encoding='utf-8')
    resources = {'greeting.txt': b'Hello, ', 'proof.txt': b'Git source resources', 'binary.dat': bytes((0, 255, 65, 128)),
                 'utf8.txt': bytes((71, 114, 195, 188, 195, 159, 101))}
    for name, raw in resources.items():
        (library / 'src' / name).write_bytes(raw)
    before = initial['src/lib.rs']
    hook = b'Ok(format!("Hello, {name}!"))'
    require(before.count(hook) == 1, 'Git-component-greeting-source-hook-changed')
    after = before.replace(hook, b'if let Some(text) = name.strip_prefix("git-proof:") {\n'
                           b'        return Ok(outside_git_component_library::describe(text));\n    }\n'
                           b'    let prefix = outside_git_component_library::prefix();\n    Ok(format!("{prefix}{name}!"))')
    (project / 'src/lib.rs').write_bytes(after)
    added = authoring.author(project, 'add', identity=PACKAGE, version=version,
                             git=REPOSITORY, revision=revision, cargo=cargo)
    authoring.author(project, 'add', identity=LOCAL_PACKAGE, version=LOCAL_VERSION, local=library, cargo=cargo)
    candidate = outside / 'candidate.json'
    lock = native.resolve(project, candidate, cargo=cargo)
    graph = json.loads((project / 'cargo-resolved.lock.json').read_bytes())
    artifact = selected(lock, graph)
    libraries = direct_libraries(graph, lock['artifacts'], {
        (PACKAGE, version): 'UnicodeXID::is_xid_start and UnicodeXID::is_xid_continue',
        (LOCAL_PACKAGE, LOCAL_VERSION): 'prefix with include_str/include_bytes'})
    raw = candidate.read_bytes()
    review.review(project, candidate, digest(raw))
    require(review.status(project)['status'] == 'verified' and (project / dependencies.LOCK).read_bytes() == raw,
            'Git-component-exact-review-mismatch')
    require((project / 'sdk-lock.json').read_bytes() == initial['sdk-lock.json'], 'Git-component-SDK-lock-mutated')
    require(library.resolve(strict=True).parent == outside.resolve(strict=True), 'Git-component-cleanup-outside-owned-root')
    shutil.rmtree(library)
    return {'formatVersion': 1, 'package': PACKAGE, 'version': version, 'revision': revision,
            'repository': REPOSITORY, 'artifactIdentity': artifact['id'], 'artifactTreeDigest': artifact['treeDigest'],
            'applicationLibraries': libraries, 'sourceDigest': digest(after), 'sdkLockDigest': digest(initial['sdk-lock.json']),
            'nativeLockDigest': digest((project / 'Cargo.lock').read_bytes()),
            'nativeGraphDigest': digest(canonical(graph)), 'candidateDigest': digest(raw),
            'resourceDigests': {name: digest(value) for name, value in resources.items()},
            'authoring': added, 'executableInputs': [], 'catalogueRegistration': False,
            'catalogueRemoval': 'not-tested', 'originalOutsideSource': 'removed-after-review'}

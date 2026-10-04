"""Real dependency qualification inputs; never application/runtime dispatch."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import tomllib

from tools.application_dependencies import LOCK
from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.build_snapshot import canonical, digest
from tools.rust_application_dependencies import resolve


DENIAL_CONTROL = r'''
    assert!(std::fs::read("/etc/passwd").is_err(), "ambient filesystem was exposed");
    for name in ["CARGO_REGISTRIES_CRATES_IO_TOKEN", "LSF_PRIVATE_TOKEN", "LSF_SIGNING_KEY"] {
        assert!(std::env::var_os(name).is_none(), "credential was inherited");
    }
    let address = std::net::SocketAddr::from(([198, 51, 100, 1], 9));
    assert!(std::net::TcpStream::connect_timeout(&address, std::time::Duration::from_millis(250)).is_err(),
            "ambient networking was exposed");
'''


def direct_libraries(graph: dict, artifacts: list[dict], required: dict[tuple[str, str], str]) -> list[dict]:
    """Bind fixture call sites to native root edges, rather than transitive presence."""
    root = graph.get('root')
    nodes = graph.get('nodes', [])
    roots = [row for row in nodes if row.get('id') == root]
    selected = graph.get('selectedResolve', {})
    selected_roots = [row for row in selected.get('nodes', []) if row.get('id') == root]
    if not root or len(roots) != 1 or selected.get('root') != root or len(selected_roots) != 1:
        raise ValueError('native Rust qualification application root is ambiguous or missing')
    direct = {digest(edge['pkg'].encode()) for edge in roots[0].get('dependencies', [])}
    direct.intersection_update(digest(edge['pkg'].encode()) for edge in selected_roots[0].get('deps', []))
    result = []
    for (name, version), ordinary_api in required.items():
        matches = [row for row in artifacts if row.get('role') == 'application'
                   and row.get('metadata', {}).get('package') == name
                   and row['metadata'].get('version') == version]
        if len(matches) != 1 or matches[0]['metadata'].get('nativeIdDigest') not in direct:
            raise ValueError('native Rust qualification library is not independently selected by the application')
        artifact = matches[0]
        provenance = [row for row in nodes if digest(row['id'].encode()) == artifact['metadata']['nativeIdDigest']]
        if len(provenance) != 1 or provenance[0].get('artifact') != artifact['id']:
            raise ValueError('native Rust qualification library artifact does not match its root edge')
        result.append({'artifact': artifact['id'], 'coordinate': name + '/' + version,
                       'ordinaryApi': ordinary_api, 'selection': 'application-root-direct'})
    return result


def install(project: Path, outside: Path, cargo: Path) -> dict:
    """Capture a normal external crate, real transitive packages and a macro."""
    # Native Unicode tables enlarge cold component preparation. Keep this
    # experiment inside the node's existing five-second ceiling; ordinary
    # project templates and the explicit 100ms interruption cases are unchanged.
    descriptor = project / 'capsule-project.json'
    recipe = json.loads(descriptor.read_bytes())
    original_wall_limit = recipe['limits']['wallTimeLimitMillis']
    recipe['limits']['wallTimeLimitMillis'] = 5000
    descriptor.write_bytes(canonical(recipe) + b'\n')
    outside.mkdir(mode=0o700)
    library, macro = outside / 'developer-owned-library', outside / 'developer-owned-macro'
    for directory in (library, macro):
        (directory / 'src').mkdir(parents=True)
    (library / 'Cargo.toml').write_text('''[package]
name = "outside-qualification-library"
version = "0.1.0"
edition = "2021"
license = "Apache-2.0"
[dependencies]
unicode-normalization = "=0.1.24"
tinyvec = "=1.10.0"
outside-qualification-macro = {path = "../developer-owned-macro"}
''', encoding='utf-8')
    resource = b'Hello, '
    (library / 'src/greeting.txt').write_bytes(resource)
    (library / 'src/lib.rs').write_text('''use unicode_normalization::UnicodeNormalization;
pub fn prefix() -> String {
    assert_eq!("\\u{212b}".nfc().collect::<String>(), "\\u{00c5}");
    let value = include_str!("greeting.txt").nfc().collect::<String>();
    assert_eq!(value, outside_qualification_macro::captured_prefix!());
    value
}
''', encoding='utf-8')
    (macro / 'Cargo.toml').write_text('''[package]
name = "outside-qualification-macro"
version = "0.1.0"
edition = "2021"
license = "Apache-2.0"
[lib]
proc-macro = true
''', encoding='utf-8')
    (macro / 'src/lib.rs').write_text('''extern crate proc_macro;
#[proc_macro]
pub fn captured_prefix(_input: proc_macro::TokenStream) -> proc_macro::TokenStream {
''' + DENIAL_CONTROL + '''
    "\\\"Hello, \\\"".parse().unwrap()
}
''', encoding='utf-8')
    (project / 'build.rs').write_text('''fn main() {
''' + DENIAL_CONTROL + '''
    let out = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::write(out.join("captured.rs"), "pub const CAPTURED_BUILD_SCRIPT: bool = true;\\n").unwrap();
    println!("cargo:rerun-if-changed=build.rs");
}
''', encoding='utf-8')
    with (project / 'Cargo.toml').open('a', encoding='utf-8') as output:
        output.write('\n[dependencies]\nunicode-normalization = "=0.1.24"\n'
                     'outside-qualification-library = {path = ' + json.dumps(str(library).replace('\\', '/')) + '}\n')
    source = project / 'src/lib.rs'
    before = source.read_bytes()
    after = before.replace(b'pub fn greet(name: String)', b'include!(concat!(env!("OUT_DIR"), "/captured.rs"));\npub fn greet(name: String)')
    after = after.replace(b'Ok(format!("Hello, {name}!"))',
                          b'assert!(CAPTURED_BUILD_SCRIPT);\n'
                          b'    let prefix = "Hello, ".nfc().collect::<String>();\n'
                          b'    assert_eq!("\\u{212b}".nfc().collect::<String>(), "\\u{00c5}");\n'
                          b'    assert_eq!(prefix, outside_qualification_library::prefix());\n'
                          b'    Ok(format!("{prefix}{name}!"))')
    if after == before or b'Ok(format!("Hello, {name}!"))' in after:
        raise ValueError('Rust dependency qualification source hook changed')
    after = b'use unicode_normalization::UnicodeNormalization;\n' + after
    source.write_bytes(after)
    pins = tomllib.loads((project / 'vendor/lsf/rust-toolchain.toml').read_text())
    # The explicit fetch stage is the sole place the native lock can advance.
    # Metadata does not execute build.rs or procedural macros.
    with tempfile.TemporaryDirectory(prefix='lsf-rust-fixture-lock-') as temporary:
        temporary = Path(temporary)
        environment = build_environment(temporary)
        environment.update(CARGO_HOME=str(temporary / 'cargo-home'), HOME=str(temporary / 'home'),
                           USERPROFILE=str(temporary / 'home'), RUSTUP_TOOLCHAIN=pins['toolchain']['channel'],
                           RUSTUP_AUTO_INSTALL='0', RUSTC=str(cargo.parent / 'rustc'))
        run_bounded([str(cargo), 'metadata', '--manifest-path', str(project / 'Cargo.toml'), '--format-version', '1'],
                    temporary, environment, 600, 16 * 1024 * 1024)
    candidate = project / 'target/qualification.candidate.json'
    candidate.parent.mkdir()
    lock = resolve(project, candidate, cargo=cargo)
    (project / LOCK).write_bytes(canonical(lock) + b'\n')
    selected = {row['metadata'].get('package') for row in lock['artifacts']}
    if not {'unicode-normalization', 'tinyvec', 'tinyvec_macros', 'outside-qualification-macro'} <= selected:
        raise ValueError('native Rust qualification graph did not capture the required transitives')
    if len(lock['executableInputs']) < 2:
        raise ValueError('root build script and application macro were not identified as executable inputs')
    application_libraries = direct_libraries(json.loads((project / 'cargo-resolved.lock.json').read_bytes()),
        lock['artifacts'], {('unicode-normalization', '0.1.24'): 'UnicodeNormalization::nfc',
                            ('outside-qualification-library', '0.1.0'): 'prefix'})
    # These roots are owned by this qualification fixture, outside the project.
    # Removing them proves the ordinary builder consumes only reviewed objects.
    for directory in (library, macro):
        if directory.resolve(strict=True).parent != outside.resolve(strict=True):
            raise ValueError('qualification cleanup escaped its owned dependency directory')
        shutil.rmtree(directory)
    return {'formatVersion': 1, 'thirdParty': 'unicode-normalization/0.1.24',
            'transitives': ['tinyvec', 'tinyvec_macros'], 'developerOwned': 'outside-qualification-library/0.1.0',
            'applicationLibraries': application_libraries,
            'resourceDigest': digest(resource), 'sourceDigest': digest(after),
            'coldPreparationBudget': {'originalWallTimeLimitMillis': original_wall_limit,
                                      'wallTimeLimitMillis': recipe['limits']['wallTimeLimitMillis'],
                                      'scope': 'dependency-qualification-greeting-only'},
            'executableInputs': lock['executableInputs'], 'offlineOriginals': 'unavailable-after-capture'}

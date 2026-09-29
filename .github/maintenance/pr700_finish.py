"""Complete the isolated repair using the observed upstream package identities."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(ROOT))
UPSTREAM = 'ebf20ab7cbf35fa3fbd8202562017fda6a541021'


def replace(name, before, after):
    path = ROOT / name
    text = path.read_text()
    assert before in text, (name, before)
    path.write_text(text.replace(before, after))


def finish():
    replace('crates/latent-wasmtime/src/values/signature.rs',
            '            Type::Map(_)\n',
            '            Type::FixedLengthList(_)\n            | Type::Map(_)\n')
    replace('crates/latent-wasmtime/src/values/encode.rs',
            '                Type::Map(_)\n',
            '                Type::FixedLengthList(_)\n                | Type::Map(_)\n')
    path = ROOT / 'crates/latent-wasmtime/src/values/tests/bounds.rs'
    text = path.read_text()
    marker = '    assert!(validate_signature(&[Type::Bool], limits, usize::MAX).is_err());'
    assert marker in text
    text = text.replace(marker, '''    // A newly exposed Wasmtime type is not an expansion of LSF's wire contract.
    // Enable it only in this reflection fixture; no Store or guest is created.
    let fixed_types = fixed_length_types();
    for ty in &fixed_types {
        assert_eq!(
            validate_signature(std::slice::from_ref(ty), limits, 1)
                .expect_err("fixed-length lists remain unsupported")
                .code,
            PlatformErrorCode::IncompatibleContract
        );
        assert_eq!(
            validate_host_signature(std::slice::from_ref(ty), limits, 1, &[])
                .expect_err("host signatures do not grant new type support")
                .code,
            PlatformErrorCode::IncompatibleContract
        );
    }
    assert_eq!(
        encode_result(&fixed_types[..1], &[Val::Bool(false)], limits)
            .err()
            .expect("unsupported result type is rejected before value encoding")
            .code,
        PlatformErrorCode::IncompatibleContract
    );
''' + marker)
    text += '''
fn fixed_length_types() -> Vec<Type> {
    use wasm_encoder::{ComponentExportKind, ComponentExportSection, ComponentTypeSection};
    use wasm_encoder::{ComponentValType, PrimitiveValType};

    let mut definitions = ComponentTypeSection::new();
    definitions
        .defined_type()
        .fixed_length_list(PrimitiveValType::U8, 4);
    definitions.defined_type().option(ComponentValType::Type(0));
    let mut exports = ComponentExportSection::new();
    exports.export("fixed", ComponentExportKind::Type, 0, None);
    exports.export("optional-fixed", ComponentExportKind::Type, 1, None);
    let mut encoded = wasm_encoder::Component::new();
    encoded.section(&definitions).section(&exports);
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_fixed_length_lists(true);
    let engine = Engine::new(&config).expect("test reflection engine");
    let component = Component::new(&engine, encoded.finish()).expect("fixed-length type fixture");
    component
        .component_type()
        .exports(&engine)
        .map(|(_, export)| {
            let ComponentItem::Type(ty) = export.ty else {
                panic!("type export expected")
            };
            ty
        })
        .collect()
}
'''
    path.write_text(text)
    # Only maintained instructions: archived benchmark/source observations and
    # versioned documentation retain the versions actually measured.
    for name in ('docs/runtime/angular-renderer-profile.md',
                 'docs/runtime/trusted-aot.md',
                 'docs/runtime/execution-security-profiles.md',
                 'docs/runtime/host-abi-profile.md',
                 'docs/testing/phase3-security.md',
                 'docs/development/phase-0-wasmtime.md'):
        replace(name, '47.0.4', '48.0.3')
    for name in ('docs/runtime/async-host-io.md', 'docs/runtime/streaming-http.md'):
        path = ROOT / name
        lines = path.read_text().splitlines(keepends=True)
        for index, line in enumerate(lines):
            if '47.0.4' in line and 'reviewed Wasmtime' in line:
                lines[index] = line.replace('47.0.4', '48.0.3')
            elif 'The baseline remains Wasmtime 47.0.4.' in line:
                lines[index] = line.replace('The baseline remains Wasmtime 47.0.4.', 'The baseline is Wasmtime 48.0.3.')
        path.write_text(''.join(lines))
    metadata = json.loads(subprocess.check_output(
        ['cargo', 'metadata', '--locked', '--format-version', '1', '--filter-platform', 'x86_64-unknown-linux-gnu'], cwd=ROOT))
    packages = {p['name']: p for p in metadata['packages'] if p['name'].startswith(('wasmtime', 'pulley-', 'cranelift-'))}
    path = ROOT / 'packaging/linux/license-sources.json'
    policy = json.loads(path.read_text())
    source = next(p for p in policy['sources'] if p['repository'] == 'https://github.com/bytecodealliance/wasmtime')
    assert source['donor']['version'] == '47.0.4'
    donor = packages['wasmtime']
    assert donor['version'] == '48.0.3'
    for name in (*source['packages'], 'wasmtime'):
        package = packages[name]
        expected = '0.135.3' if name.startswith('cranelift-') else '48.0.3'
        assert package['version'] == expected
        vcs = json.loads((Path(package['manifest_path']).parent / '.cargo_vcs_info.json').read_text())
        assert vcs['git']['sha1'] == UPSTREAM, (name, vcs)
        assert package['license'] == source['license'], name
        if name in source['packages']:
            source['packages'][name] = expected
    license_bytes = (Path(donor['manifest_path']).parent / source['donor']['file']).read_bytes()
    assert hashlib.sha256(license_bytes).hexdigest() == source['sha256']
    source['donor']['version'] = donor['version']
    source['sourceCommit'] = UPSTREAM
    source['sourceUrl'] = source['repository'] + '/blob/' + UPSTREAM + '/LICENSE'
    path.write_text(json.dumps(policy, indent=2) + '\n')
    from tools.native_runtime_build import dependency_inventory
    lock = tomllib.loads((ROOT / 'Cargo.lock').read_text())
    sbom, licenses = dependency_inventory(metadata, lock, '5c7aaa47243fa1ebf760dce314fbfda44be7a71a', 1790678400, policy)
    assert any(p['name'] == 'wasmtime' and p['versionInfo'] == '48.0.3' for p in sbom['packages'])
    assert licenses
    print(f"Validated actual native dependency inventory: {len(sbom['packages'])} packages; {len(licenses)} license files.")
    report = ROOT / 'docs/development/wasmtime-security-update.md'
    text = report.read_text()
    needle = 'No advisory exception, ignored finding or skipped security gate is introduced.'
    assert needle in text
    report.write_text(text.replace(needle, needle + '''
The new fixed-length-list reflection variant is explicitly rejected by signature
admission and result encoding; the supported invocation wire types do not grow.
A real encoded-component regression checks direct and nested rejection before
any Store is created. Native shared-license policy follows the exact published
Wasmtime/Cranelift revision and verifies its unchanged root license digest.
'''))
    subprocess.run(['cargo', 'fmt', '--all'], cwd=ROOT, check=True)


def compact():
    path = ROOT / 'tools/ci/commands.json'
    original = json.loads(subprocess.check_output(['git', 'show', 'HEAD:tools/ci/commands.json'], cwd=ROOT))
    updated = json.loads(path.read_text())

    def ordered(old, new):
        if isinstance(new, dict):
            old = old if isinstance(old, dict) else {}
            keys = [key for key in old if key in new] + [key for key in new if key not in old]
            return {key: ordered(old.get(key), new[key]) for key in keys}
        return new

    path.write_text(json.dumps(ordered(original, updated), indent=2) + '\n')
    assert json.loads(path.read_text()) == updated
    from tools.ci_coverage import validate
    validate(ROOT, path)


{'finish': finish, 'compact': compact}[sys.argv[1]]()

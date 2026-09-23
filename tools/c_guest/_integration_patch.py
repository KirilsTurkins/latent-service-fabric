"""One-use feature-branch integration edits; removed after applying."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
NAMES = ['blob', 'callee', 'events', 'http', 'metrics', 'random', 'secrets', 'service', 'streaming', 'application']


def replace(path, old, new):
    path = ROOT / path
    text = path.read_text()
    assert text.count(old) == 1, (path, old)
    path.write_text(text.replace(old, new))


def wrap(path, function, transform):
    path = ROOT / path
    text = path.read_text()
    start = text.index('async fn ' + function + '(')
    body = text.index('{\n', start) + 2
    end = text.index('\n}', body)
    contents = transform(text[body:end])
    contents = ''.join('    ' + line if line.strip() else line for line in contents.splitlines(True))
    text = text[:body] + '    for language in ["rust", "c"] {\n' + contents + '\n    }' + text[end:]
    path.write_text(text)


for name, function in {
    'http': 'buffered_http_success_and_denial_use_the_real_provider',
    'streaming': 'streaming_ownership_and_independent_chunks_survive_body_drop',
    'secrets': 'secret_owner_typed_denial_cancellation_and_cell_recovery',
    'events': 'typed_event_receipt_denial_and_uncertainty_do_not_retry',
    'random': 'generated_random_binding_and_reused_cell',
    'metrics': 'generated_metric_kinds_and_typed_failure',
}.items():
    def transform(text, name=name):
        old = '"rust-' + name + '"'
        assert text.count(old) == 1
        return text.replace(old, '&format!("{language}-' + name + '")')
    wrap('crates/latent-wasmtime/tests/guest_sdk/' + name + '.rs', function, transform)

service = 'crates/latent-wasmtime/tests/guest_sdk/service.rs'
replace(service, 'async fn configured(root: &std::path::Path, permit: bool)',
        'async fn configured(root: &std::path::Path, permit: bool, language: &str)')
replace(service, '    let caller = package::bundle(&package::input("rust-service"));\n    let callee = package::bundle(&package::input("rust-callee"));\n    let signers = package::Signers::new(latent_signing::RUST_GUEST_BUILD_TYPE);',
        '    let caller_name = format!("{language}-service");\n    let callee_name = format!("{language}-callee");\n    let caller = package::bundle(&package::input(&caller_name));\n    let callee = package::bundle(&package::input(&callee_name));\n    let signers = package::Signers::new(if language == "c" { latent_signing::C_GUEST_BUILD_TYPE } else { latent_signing::RUST_GUEST_BUILD_TYPE });')
replace(service, '[("rust-service", &caller), ("rust-callee", &callee)]',
        '[(caller_name.as_str(), &caller), (callee_name.as_str(), &callee)]')
wrap(service, 'typed_service_outcomes_use_node_admission_and_reused_cells',
     lambda text: text.replace('configured(root.path(), permit)', 'configured(root.path(), permit, language)'))
wrap('crates/latent-wasmtime/tests/guest_sdk.rs', 'all_rust_examples_are_exact_signed_phase2_packages',
     lambda text: text.replace('format!("rust-{name}")', 'format!("{language}-{name}")'))

replace('crates/latent-signing/src/provenance/validate.rs', 'p.fixture == "blob"',
        'matches!(p.fixture.as_str(), ' + ' | '.join(json.dumps(name) for name in NAMES) + ')')
for name in ('build-observation', 'package-provenance-statement'):
    path = ROOT / ('schemas/' + name + '.schema.json')
    value = json.loads(path.read_text())
    count = 0
    def visit(item):
        global count
        if isinstance(item, dict):
            if 'properties' in item and 'fixture' in item['properties']:
                fixture = item['properties']['fixture']
                assert fixture.get('const') == 'blob', fixture
                fixture.pop('const')
                fixture['enum'] = NAMES
                count += 1
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
    visit(value)
    assert count == 1, (name, count)
    path.write_text(json.dumps(value, indent=2) + '\n')

path = 'tools/build_guest_capsules.py'
replace(path, 'import time\n', 'import time\nimport tempfile\n')
replace(path, 'from tools.stage_runtime_wit import stage',
        'from tools.stage_runtime_wit import stage\nfrom tools.c_guest.compiler import Compiler, CAPABILITIES')
replace(path, '"sdk/rust-guest", "sdk/c-guest", "crates/latent-component-bindings",',
        '"sdk/rust-guest", "sdk/c-guest", "tools/c_guest", "crates/latent-component-bindings",')
replace(path, 'and "target" not in path.relative_to(ROOT / directory).parts)',
        'and not {"target", "__pycache__"}.intersection(path.relative_to(ROOT / directory).parts)\n                     and path.suffix != ".pyc")')
replace(path, '"compiler": "zig-cc", "fixture": "blob",',
        '"compiler": "zig-cc", "fixture": profile["name"],')
replace(path, 'build_c(output, next(p for p in profiles if p["name"] == "blob"), sources)',
        'build_c(output, profiles, sources)')
replace(path, '([] if args.skip_c else ["c-blob"])',
        '([] if args.skip_c else ["c-" + name for name in CAPABILITIES])')
p = ROOT / path
text = p.read_text()
start, end = text.index('def build_c('), text.index('\n\nif __name__ == "__main__":')
text = text[:start] + '''def build_c(output: Path, profiles: list[dict], sources: bytes) -> None:
    by_name = {profile["name"]: profile for profile in profiles}
    if set(by_name) != set(CAPABILITIES):
        raise ValueError("C and Rust guest capability inventories differ")
    remaining = int(BUILD_DEADLINE - time.monotonic())
    if remaining < 1:
        raise ValueError("guest build deadline exceeded")
    with tempfile.TemporaryDirectory(prefix="c-components-", dir=output) as temporary:
        temporary = Path(temporary)
        compiler = Compiler(temporary / "tmp", min(remaining, 900))
        for name in CAPABILITIES:
            started = int(time.time())
            profile = by_name[name]
            source = ROOT / "sdk/c-guest/blob.c" if name == "blob" else ROOT / "sdk/c-guest/examples" / (name + ".c")
            component, lock = compiler.compile([source], EXAMPLES / ("guest_" + name),
                profile["world"], temporary / name,
                memory_bytes=4_194_304 if name in {"service", "callee"} else 16_777_216,
                trap=name != "blob")
            destination = output / ("c-" + name)
            package_inputs(destination, profile, EXAMPLES / ("guest_" + name) / "world.wit", component)
            write_json(destination / "bindings.json", lock)
            observation(output, destination, profile, component, started, sources, "c")
''' + text[end:]
p.write_text(text)

path = 'crates/latent-signing/tests/guest_provenance.rs'
replace(path, '    let value = serde_json::to_value(observation()).unwrap();', '''    for fixture in ["blob", "callee", "events", "http", "metrics", "random", "secrets", "service", "streaming", "application"] {
        let mut observation = guest(true);
        let BuildRecipe::C(parameters) = &mut observation.parameters else { unreachable!() };
        parameters.fixture = fixture.into();
        let evidence = signed(&signer, &observation);
        let mut policy = policy_value(&public);
        assert_eq!(verifier(&policy).verify_package(&subject(), evidence.as_ref(), NOW).unwrap_err().reason(), SignatureFailure::PredicateDisallowed);
        policy["requirements"][0]["buildType"] = C_GUEST_BUILD_TYPE.into();
        verifier(&policy).verify_package(&subject(), evidence.as_ref(), NOW).unwrap();
    }
    let value = serde_json::to_value(observation()).unwrap();''')
replace(path, '    for c in [false, true] {\n        let valid = guest(c);', '''    for invalid in ["arbitrary", "../blob", "", "application;sh"] {
        let mut value = serde_json::to_value(guest(true)).unwrap();
        value["parameters"]["fixture"] = invalid.into();
        assert!(decode_build_observation(&serde_json::to_vec(&value).unwrap(), Default::default()).is_err());
    }
    for c in [false, true] {
        let valid = guest(c);''')
print('Applied reviewed C runtime and provenance integration edits')

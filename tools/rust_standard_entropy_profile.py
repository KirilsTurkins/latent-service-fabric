"""Exact compiler/runtime-package source derivation for declared Rust entropy."""
import hashlib
import json

from tools.dev_workflow.common import digest, encode, require
from tools.rust_capsule_project import ROOT, inventory, read_file

PROFILE = 'lsf-rust-standard-entropy-source-v1'
RANDOM = 'latent:random/random@0.1.0'
ORIGINALS = {
    'std/src/sys/random/mod.rs': '58e6c9fa2f0a5eaa796c5a6172a0b25ef59fc47c6d9ca2e78e93ba23ef7c094f',
    'std/src/sys/random/unsupported.rs': '26c9c231cc3f23a0815ac28dbac9e4f2d53c09ee56510c954b38f856cd593e50',
}
GETRANDOM = {
    'formatVersion': 1, 'runtimePackage': 'getrandom', 'version': '0.3.4',
    'archiveSha256': '899def5c37c4fd7b2664648c28120ecec138e4d395b459e5ca34f9cce2dd77fd',
    'archiveBytes': 50932,
    'originals': {
        'build.rs': {'sha256': 'd542c9c3bbc2f64a26c758eac8af16178aab52464bdd8bf0b9a767ba87665021', 'bytes': 2173},
        'src/backends.rs': {'sha256': '61f8d982cd502f3229f49bef2f9b40e181c7c16fb41d029aa2e77f32b10c10a6', 'bytes': 7789},
        'src/backends/custom.rs': {'sha256': 'c8776ff0dda65cef1373b8624043f8a42ce4fd6183fbeb8918f9df5d4a13d457', 'bytes': 434},
        'src/backends/unsupported.rs': {'sha256': 'a531ab9883b7d7b584c6f37a5c13543ec63d25d3acc36608d57d5d82ef44cbff', 'bytes': 238},
        'src/error.rs': {'sha256': '43f4918d3c47d211d223543fa4b93074f883dcb7232b673b03c8b7fe19ef8e7a', 'bytes': 8837},
    },
}
RECIPE = ('tools/rust_standard_entropy_profile.py',
    'sdk/rust-standard-runtime/entropy_core.rs', 'sdk/rust-standard-runtime/entropy_std.rs',
    'sdk/rust-standard-runtime/entropy_getrandom_03.rs',
    'sdk/rust-standard-runtime/entropy-getrandom-03.json', 'wit/platform/random/package.wit')
SELECTOR = b'all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "")'


def recipe():
    inputs = {name: read_file(ROOT / name) for name in RECIPE}
    require(json.loads(inputs['sdk/rust-standard-runtime/entropy-getrandom-03.json']) == GETRANDOM,
            'rust-entropy-runtime-package-profile')
    return inputs


def overlay(original, inputs):
    require(set(original) == set(ORIGINALS), 'rust-entropy-std-original-set')
    for name, raw in original.items():
        require(hashlib.sha256(raw).hexdigest() == ORIGINALS[name], 'rust-entropy-std-preimage')
    source = original['std/src/sys/random/mod.rs']
    marker = b'    any(\n        all(target_family = "wasm", target_os = "unknown"),'
    require(source.count(marker) == 1, 'rust-entropy-std-selector-preimage')
    branch = b'    ' + SELECTOR + b' => {\n        mod lsf;\n        pub use lsf::{fill_bytes, hashmap_random_keys};\n    }\n'
    return {'std/src/sys/random/mod.rs': source.replace(marker, branch + marker, 1),
            'std/src/sys/random/lsf.rs': inputs['sdk/rust-standard-runtime/entropy_core.rs'] + b'\n'
                + inputs['sdk/rust-standard-runtime/entropy_std.rs']}


def getrandom_overlay(files, inputs):
    """The complete original registry capture is authenticated before this call.

    Only this versioned runtime package is ported. Other application package
    identities remain unrestricted. No caller-selected backend code executes.
    """
    for name, expected in GETRANDOM['originals'].items():
        raw = files.get(name)
        require(isinstance(raw, bytes) and len(raw) == expected['bytes']
                and hashlib.sha256(raw).hexdigest() == expected['sha256'],
                'rust-entropy-getrandom-preimage')
    checksum = json.loads(files['.cargo-checksum.json'])
    require(checksum['package'] == GETRANDOM['archiveSha256']
            and checksum['files'] == {name: hashlib.sha256(raw).hexdigest()
                for name, raw in files.items() if name != '.cargo-checksum.json'},
            'rust-entropy-getrandom-vendor-checksum')
    source = files['src/backends.rs']
    marker = b'    } else if #[cfg(all(target_arch = "wasm32", any(target_os = "unknown", target_os = "none")))] {'
    require(source.count(marker) == 1, 'rust-entropy-getrandom-selector-preimage')
    branch = b'    } else if #[cfg(' + SELECTOR + b')] {\n        mod custom;\n        pub use custom::*;\n'
    changes = {'src/backends.rs': source.replace(marker, branch + marker, 1),
        'src/backends/custom.rs': inputs['sdk/rust-standard-runtime/entropy_core.rs'] + b'\n'
            + inputs['sdk/rust-standard-runtime/entropy_getrandom_03.rs']}
    updated = {**files, **changes}
    checksum['files'] = {name: hashlib.sha256(raw).hexdigest()
        for name, raw in updated.items() if name != '.cargo-checksum.json'}
    changes['.cargo-checksum.json'] = encode(checksum)
    return changes


def material(inputs):
    return {'profile': PROFILE, 'recipeDigest': digest(inventory(inputs)),
        'requiredDeclaration': RANDOM, 'canonicalResultBytes': 16, 'maximumBufferBytes': 65536,
        'runtimePackage': GETRANDOM}


def runtime_package(row):
    metadata = row.get('metadata', {})
    return (row.get('format') == 'directory' and metadata.get('ecosystem') == 'cargo'
            and metadata.get('package') == GETRANDOM['runtimePackage']
            and metadata.get('version') == GETRANDOM['version']
            and metadata.get('vendorChecksum', {}).get('package') is not None)


def captured_changes(row, files, profile):
    from tools.rust_standard_logging_inputs import has_entropy
    if not has_entropy(profile) or not runtime_package(row):
        return {}, None
    require(row['metadata']['vendorChecksum']['package'] == GETRANDOM['archiveSha256'],
            'rust-entropy-unreviewed-runtime-package')
    inputs = recipe()
    return getrandom_overlay(files, inputs), material(inputs)


def verify_capture(verified, profile):
    """Reproduce current runtime edits from authenticated original CAS bytes.

    Capture metadata and a version string cannot authorize substituted backend
    code. Normal application/local packages are not selected by this boundary.
    """
    from tools.rust_standard_logging_inputs import has_entropy
    selected = has_entropy(profile)
    transforms = verified.lock['transformations']
    for transform in transforms:
        if 'runtimeEntropyPort' in transform['selection']:
            require(selected, 'rust-entropy-port-without-selected-profile')
    for row in verified.lock['artifacts']:
        if not selected or not runtime_package(row):
            continue
        original_rows = json.loads(verified.store.get(**row['original']))
        files = {item['path']: verified.store.get(item['digest'], item['size']) for item in original_rows}
        changes, expected = captured_changes(row, files, profile)
        actual = {item['path']: item for item in row['files']}
        if actual['Cargo.toml']['digest'] != digest(files['Cargo.toml']):
            checksum = json.loads(changes['.cargo-checksum.json'])
            checksum['files']['Cargo.toml'] = actual['Cargo.toml']['digest'][7:]
            from tools.build_snapshot import canonical
            changes['.cargo-checksum.json'] = canonical(checksum) + b'\n'

        ports = [t for t in transforms if t['artifact'] == row['id'] and 'runtimeEntropyPort' in t['selection']]
        require(len(ports) == 1 and ports[0]['selection']['runtimeEntropyPort'] == expected,
                'rust-entropy-captured-runtime-recipe-drift')
        require(all(name in actual and actual[name]['digest'] == digest(raw)
                    and actual[name]['size'] == len(raw) for name, raw in changes.items()),
                'rust-entropy-captured-runtime-output-drift')
        require(set(changes) <= {item['path'] for item in ports[0]['changes']}
                <= {*changes, 'Cargo.toml'}, 'rust-entropy-captured-runtime-change-set')

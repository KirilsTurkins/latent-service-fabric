"""Select the maintained URL aggregate without changing dependency resolution."""
from __future__ import annotations
import hashlib
import tomllib

PREIMAGES = {
    'original-aggregate-Cargo.lock': '46a469ce88f8334da3cd64872191b927eb969c84f8c08b58c8ec2501b205b30a',
    'original-aggregate-Cargo.toml.in': '8d8e5315a0452c03ea86ddc5165489ef7c4d56af2d6a675484cf383285a8a200',
    'original-aggregate.rs.in': 'a7f37d966d3a3a2496514d74f21c2168dfab7fd859d5eb5bf84812fd4020d500',
}
CRATES = ('rust-encoding', 'rust-hooks', 'rust-url')


def derive(original: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    if set(original) != set(PREIMAGES):
        raise ValueError('exact-maintained-URL-aggregate-required')
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError('unreviewed-maintained-URL-aggregate:' + name)
    raw = original['original-aggregate-Cargo.lock']
    packages = {row['name']: row for row in tomllib.loads(raw.decode())['package']}
    retain = set(CRATES) | {'rust-staticlib'}
    pending = list(CRATES)
    while pending:
        for dependency in packages[pending.pop()].get('dependencies', []):
            if dependency not in packages:
                raise ValueError('ambiguous-maintained-URL-dependency')
            if dependency not in retain:
                retain.add(dependency)
                pending.append(dependency)
    chunks = raw.split(b'[[package]]')
    lock = chunks[0]
    for chunk in chunks[1:]:
        name = tomllib.loads((b'[[package]]' + chunk).decode())['package'][0]['name']
        if name not in retain:
            continue
        if name == 'rust-staticlib':
            if chunk.count(b' "multipart",\n') != 1:
                raise ValueError('maintained-URL-aggregate-root-shape')
            chunk = chunk.replace(b' "multipart",\n', b'', 1)
        lock += b'[[package]]' + chunk
    expected = [dict(row, dependencies=list(CRATES)) if row['name'] == 'rust-staticlib' else row
                for row in packages.values() if row['name'] in retain]
    if tomllib.loads(lock.decode())['package'] != expected:
        raise ValueError('changed-maintained-URL-package-graph')
    manifest = original['original-aggregate-Cargo.toml.in']
    anchor = b'name = "rust-staticlib"\n'
    if manifest.count(anchor) != 1:
        raise ValueError('maintained-URL-manifest-shape')
    manifest = manifest.replace(anchor, anchor + b'version = "0.0.0"\n', 1)
    manifest += b''.join(f'{name} = {{ path = "crates/{name}" }}\n'.encode() for name in CRATES)
    source = original['original-aggregate.rs.in'] + b''.join(
        f'pub use {name.replace("-", "_")};\n'.encode() for name in CRATES)
    return {'Cargo.lock': lock, 'Cargo.toml': manifest, 'rust-staticlib.rs': source}, {
        'qualification': 'unknown', 'selectedCrates': list(CRATES),
        'selectedVersionsAndChecksumsPreserved': True, 'selectedPackageCount': len(retain),
        'separateDuplicateRustArchives': False, 'multipartSelected': False,
    }

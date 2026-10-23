"""Authenticate the one host-only bytes owner-retirement source fork."""
from __future__ import annotations

from pathlib import Path
import stat
import tomllib

from tools.security_common import SecurityError, decode_json, digest, read_file, require

PROVIDER = 'crates/vendor/bytes'
MANIFEST = PROVIDER + '/Cargo.toml'
VERSION = '1.12.1'
ARCHIVE_SHA256 = 'fc652a48c352aef3ea3aed32080501cf3ef6ed5da78602a020c991775b0aff04'
RECORD_SHA256 = '4998d6526aa21969ea021d4f781fa36ebaf64b2e7ceeea67daee0f4b51b6c2d3'
HOST_PATCH = {'bytes': {'path': PROVIDER}}
REGISTRY_PACKAGE = {'name': 'bytes', 'version': VERSION,
    'source': 'registry+https://github.com/rust-lang/crates.io-index',
    'checksum': ARCHIVE_SHA256}
POSTIMAGES = {
    'Cargo.toml': {'bytes': 2601, 'sha256': '989921f4afccdec4c5076d4ded65428b22ff42899475eeff847e7bd2cc68ace6'},
    'src/bytes.rs': {'bytes': 52468, 'sha256': '8868b252f0c21802d2e01cdcee98b218e36e6830ec105b2902a42e7a6ecc9831'},
    'PHYSICAL-RETIREMENT.md': {'bytes': 1958, 'sha256': '55a96c57290f9f460e5477421bad0cd4a0435b7fb5d41206a156033e34ba2bf6'},
    'tests/test_owner_retirement.rs': {'bytes': 6621, 'sha256': '66f36dfe3b5f82fcf4ef6db0b6b6454e94719af8a0db2a93cd1e7856cdae8b42'},
}


def verify(repo: Path) -> dict:
    try:
        return _verify(repo)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise SecurityError('unreviewed-result-bytes-source') from error


def _verify(repo: Path) -> dict:
    repo = repo.resolve(strict=True)
    raw = read_file(repo, PROVIDER + '/UPSTREAM.json', 16384).replace(b'\r\n', b'\n')
    require(digest(raw) == RECORD_SHA256, 'unreviewed-result-bytes-origin-record')
    origin = decode_json(raw)
    require(set(origin) == {'name', 'version', 'crateSha256', 'source', 'originalFiles'}
            and origin['name'] == 'bytes' and origin['version'] == VERSION
            and origin['crateSha256'] == ARCHIVE_SHA256
            and origin['source'] == 'https://static.crates.io/crates/bytes/bytes-1.12.1.crate'
            and len(origin['originalFiles']) == 38, 'unreviewed-result-bytes-origin')
    files = {**origin['originalFiles'], **POSTIMAGES,
             'UPSTREAM.json': {'bytes': len(raw), 'sha256': RECORD_SHA256}}
    require(len(files) == 41, 'unreviewed-result-bytes-membership')
    expected_directories = {PROVIDER}
    for name in files:
        expected_directories.update(PROVIDER + '/' + parent.as_posix()
            for parent in Path(name).parents if parent != Path('.'))
    pending, directories, observed = [repo / PROVIDER], set(), set()
    while pending:
        directory = pending.pop()
        directories.add(directory.relative_to(repo).as_posix())
        require(len(directories) <= 32, 'unreviewed-result-bytes-membership')
        for path in directory.iterdir():
            metadata = path.lstat()
            require(not stat.S_ISLNK(metadata.st_mode)
                    and not getattr(metadata, 'st_file_attributes', 0) & 0x400,
                    'linked-result-bytes-source')
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            else:
                require(stat.S_ISREG(metadata.st_mode), 'nonregular-result-bytes-source')
                observed.add(path.relative_to(repo).as_posix())
            require(len(pending) <= 32 and len(observed) <= 64,
                    'unreviewed-result-bytes-membership')
    require(directories == expected_directories
            and observed == {PROVIDER + '/' + name for name in files},
            'unreviewed-result-bytes-membership')
    for name, expected in files.items():
        payload = read_file(repo, PROVIDER + '/' + name, 1024 * 1024)
        if name == 'UPSTREAM.json':
            payload = payload.replace(b'\r\n', b'\n')
        require({'bytes': len(payload), 'sha256': digest(payload)} == expected,
                'unreviewed-result-bytes-source')
    manifest = tomllib.loads(read_file(repo, MANIFEST).decode())
    require((manifest['package']['name'], manifest['package']['version']) == ('bytes', VERSION),
            'unreviewed-result-bytes-package')
    workspace = tomllib.loads(read_file(repo, 'Cargo.toml').decode())
    require(workspace.get('patch') == {'crates-io': HOST_PATCH}
            and workspace['workspace']['dependencies']['bytes'] == '=' + VERSION
            and PROVIDER in workspace['workspace']['exclude'], 'unreviewed-result-bytes-host-patch')
    rows = [row for row in tomllib.loads(read_file(repo, 'Cargo.lock').decode())['package']
            if row['name'] == 'bytes']
    require(rows == [{'name': 'bytes', 'version': VERSION}], 'unreviewed-result-bytes-build-lock')
    return {'name': 'bytes', 'version': VERSION, 'checksum': ARCHIVE_SHA256,
            'recordSha256': RECORD_SHA256, 'manifestSha256': files['Cargo.toml']['sha256'],
            'files': files, 'buildLock': 'Cargo.lock'}

from pathlib import Path
from datetime import datetime, timezone
import fcntl, hashlib, json, os, stat, time, zipfile
base = Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
source = Path('/root-checks/integration-v12-current-java-tools-custody')
root = base / 'jobs/integration-v12-current-java-tools-v1'
assert os.getuid() == 10001 and os.getgid() == 10001 and not root.exists()
lock = (base / 'jobs/root-native-active-v2.lock').open('a+')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
root.mkdir(mode=0o700)
deadline = time.monotonic() + 900
archive = source / 'managed.zip'
with archive.open('rb') as raw:
    assert hashlib.file_digest(raw, 'sha256').hexdigest() == 'c58bb7a214b6ede7db5180cf13924f9b70838070287fdc71c636f03d643ca63d'
manifest = json.loads((source / 'managed-inputs.json').read_bytes())
assert manifest['identity'] == 'sha256:86ea1752a6fce2311eb3a9a0331361477a0ec919db57f516cb5144b8e5eef035'
raw_identity = json.dumps({k: v for k, v in manifest.items() if k != 'identity'}, ensure_ascii=True, separators=(',', ':'), sort_keys=True, allow_nan=False).encode() + b'\n'
assert 'sha256:' + hashlib.sha256(raw_identity).hexdigest() == manifest['identity']
expected = {row['path']: row for row in manifest['files']}
assert len(expected) == len(manifest['files']) == 10966
assert sum(row['size'] for row in expected.values()) == 1072732888
with zipfile.ZipFile(archive) as captured:
    assert set(captured.namelist()) == set(expected)
    for item in captured.infolist():
        assert time.monotonic() < deadline
        name = Path(item.filename)
        assert not name.is_absolute() and '..' not in name.parts and ':' not in item.filename
        assert stat.S_IFMT(item.external_attr >> 16) != stat.S_IFLNK
        row = expected[item.filename]
        destination = root / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        size = 0
        digest = hashlib.sha256()
        with captured.open(item) as inp, destination.open('xb') as out:
            while chunk := inp.read(1024 * 1024):
                size += len(chunk)
                assert size <= row['size']
                digest.update(chunk)
                out.write(chunk)
        assert size == row['size'] and 'sha256:' + digest.hexdigest() == row['sha256']
        destination.chmod(0o700 if row['executable'] else 0o600)
(root / 'bin').mkdir(mode=0o700)
metadata = json.loads((source / 'developer-bundle.json').read_bytes())
identities = {row['path']: row for row in metadata['files']}
with zipfile.ZipFile(source / metadata['archive']['name']) as bundle:
    for name in ['wasm-tools', 'wit-bindgen']:
        original = 'sdk/bin/' + name
        raw = bundle.read(original)
        row = identities[original]
        assert len(raw) == row['size'] and 'sha256:' + hashlib.sha256(raw).hexdigest() == row['sha256']
        destination = root / 'bin' / name
        destination.write_bytes(raw)
        destination.chmod(0o700)
receipt = dict(at=datetime.now(timezone.utc).isoformat(), uid=os.getuid(), root=str(root),
    files=len(expected), logicalBytes=sum(row['size'] for row in expected.values()),
    originalToolIdentity=manifest['identity'], originalFilesByteIdentical=True,
    sourceCheckoutMutated=False, compilersExecuted=False, compiledQualification=False)
(root / 'stage-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
fcntl.flock(lock, fcntl.LOCK_UN)
lock.close()

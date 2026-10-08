from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

coord = Path(__file__).resolve().parent
target = coord / "phase4-v12-windows-native-target"
receipt_path = coord / "integration-v12-823/windows-wire-check-receipt.json"
raw = receipt_path.read_bytes()
receipt = json.loads(raw)
assert receipt["reaped"] and receipt["exit"] == 0 and receipt["stopReason"] is None
assert target.resolve() == Path(receipt["targetPath"]).resolve() and target.resolve().parent == coord.resolve()
assert target.is_dir() and not target.is_symlink()
log = (receipt_path.parent / "windows-wire-check.log").read_bytes()
assert hashlib.sha256(log).hexdigest() == receipt["logSha256"]
assert subprocess.check_output(["git", "cat-file", "-t", receipt["head"]], cwd=Path(r"C:\Users\turkins\Desktop\latent-fabric")).strip() == b"commit"
files = []
for path in sorted(target.rglob("*")):
    assert not path.is_symlink()
    if path.is_file():
        size = path.stat().st_size
        assert size <= 512 * 1024 ** 2
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files.append(dict(path=path.relative_to(target).as_posix(), bytes=size, sha256=digest))
proof = dict(at=datetime.now(timezone.utc).isoformat(), target=str(target.resolve()), originalHead=receipt["head"],
    originalReceiptSha256=hashlib.sha256(raw).hexdigest(), originalRawLogAuthenticated=True,
    originalProcessReaped=True, originalSourceCommitPreserved=True, onlyReconstructibleCargoOutput=True,
    fileCount=len(files), bytes=sum(row["bytes"] for row in files), files=files,
    gitSourceRawLogsReceiptsAndCurrentArtifactsOutsideTarget=True, retirementAuthorizedWithinOwnedDisposableCache=True)
path = coord / "integration-v12-union-review/private-windows-target-retirement-audit-v19.json"
path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps({key:value for key,value in proof.items() if key != "files"}))

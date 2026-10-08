"""Observe host disk; below1GiB stop only this job's verified owned log groups."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time

coord = Path(__file__).resolve().parent
owner = "latent-p4-root-native-20261007-v6"
job = "integration-v12-current-java-real-node-v19"
out = coord / job
body = r'''
import json, os, signal
from pathlib import Path
base = Path("/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data")
source = base / "native-active-portable-v3"
logs = base / "jobs/integration-v12-current-java-real-node-v19"
groups = {}
for path in Path("/proc").iterdir():
    if not path.name.isdigit():
        continue
    try:
        pid = int(path.name)
        cwd = (path / "cwd").resolve()
        if cwd != source:
            continue
        selected = []
        for number in (1, 2):
            try:
                selected.append(os.readlink(path / "fd" / str(number)))
            except OSError:
                pass
        owned = [value for value in selected if value.startswith(str(logs) + "/step-") and value.endswith(".log")]
        if owned:
            group = os.getpgid(pid)
            if group > 1 and group != os.getpgrp():
                groups.setdefault(group, []).append(dict(pid=pid, cwd=str(cwd), logFds=owned))
    except (OSError, ProcessLookupError):
        pass
custody = dict(identifiedGroups=groups, noGlobalSignals=True, exactOwnedJobOnly=True)
(logs / "disk-stop-owned-groups.json").write_text(json.dumps(custody, indent=2) + "\n")
print(json.dumps(custody), flush=True)
for group in groups:
    try:
        os.killpg(group, signal.SIGTERM)
    except ProcessLookupError:
        pass
'''
start = time.monotonic()
rows = []
stop = None
while time.monotonic() - start < 240:
    free = shutil.disk_usage(coord).free
    rows.append(dict(at=datetime.now(timezone.utc).isoformat(), freeBytes=free))
    if (out / "receipt.json").exists():
        stop = "original-job-already-final"
        break
    if free < 1024 ** 3:
        stop = "host-disk-below-one-GiB"
        result = subprocess.run(["docker", "exec", "-i", "--user", "10001:10001", owner, "python3", "-X", "utf8", "-B"],
            input=body.encode(), capture_output=True, timeout=30)
        (out / "disk-stop-controller.log").write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0
        break
    time.sleep(10)
proof = dict(job=job, observations=rows, stopReason=stop, maximumMonitorSeconds=240,
    onlyExactJobGroupsSignalled=stop == "host-disk-below-one-GiB", noCleanupOrEngineAction=True)
(coord / "integration-v12-union-review/own-native-disk-monitor-v19.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(dict(job=job, stopReason=stop, lastFreeBytes=rows[-1]["freeBytes"], noCleanupOrEngineAction=True)))

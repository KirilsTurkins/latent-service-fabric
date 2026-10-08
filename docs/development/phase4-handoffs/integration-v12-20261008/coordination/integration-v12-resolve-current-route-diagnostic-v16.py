"""Preserve both bounded route diagnostic collectors across the main merge."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
coord = Path(__file__).resolve().parent
tag = sys.argv[2]
assert root.parent == Path(r"C:\Users\turkins\Desktop") and tag in {"pr823", "pr828"}
path = "tools/java_server_node.py"
def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)
assert git("diff", "--name-only", "--diff-filter=U").decode().splitlines() == [path]
custody = coord / "integration-v12-union-review" / (tag + "-current-route-diagnostic-stages-v16")
custody.mkdir()
raws = {}
for stage in (1, 2, 3):
    raw = git("show", ":" + str(stage) + ":" + path)
    (custody / ("stage-" + str(stage) + ".py")).write_bytes(raw)
    raws[str(stage)] = hashlib.sha256(raw).hexdigest()
target = root / path
source = target.read_text(encoding="utf8")
start = source.index("<<<<<<< HEAD\n")
split = source.index("=======\n", start)
end = source.index(">>>>>>> ", split)
endline = source.index("\n", end)
ours = source[start + len("<<<<<<< HEAD\n"):split]
assert "route_observation_bytes = 0" in ours and "observer=observe_route_call" in ours
old = 'route_cli = RouteClient(binary, client.config, root / "routes", deadline=client.deadline,\n                                    observer=observe_route_call)'
new = 'route_cli = ObservedRouteClient(binary, client.config, root / "routes", deadline=client.deadline,\n                                            evidence=evidence, observer=observe_route_call)'
assert ours.count(old) == 1
resolved = source[:start] + ours.replace(old, new) + source[endline + 1:]
assert all(marker not in resolved for marker in ("<<<<<<<", "=======", ">>>>>>>"))
assert resolved.count("class ObservedRouteClient(RouteClient):") == 1
assert "route-delete-rejection.json" in resolved and '"route-control-"' in resolved
assert "routeFailedCall=route_cli.failed_call" in resolved and "routeObservationFailed=" in resolved
compile(resolved, path, "exec")
target.write_text(resolved, encoding="utf8", newline="\n")
git("add", "--", path)
git("commit", "--no-edit")
head = git("rev-parse", "HEAD").decode().strip()
assert not git("status", "--porcelain").strip()
(custody / "review.json").write_text(json.dumps(dict(head=head, stagesSha256=raws,
    bothBoundedCollectorsRetained=True, originalDeadlineAndObserverLimitsPreserved=True,
    rawPayloadAndArgumentsNotAdded=True, singleCallNoRetryPreserved=True), indent=2) + "\n", encoding="utf8")
print(json.dumps(dict(head=head, custody=str(custody))))

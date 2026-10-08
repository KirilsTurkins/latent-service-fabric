import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
out = coord / "integration-v12-current823-dotnet-host-v16"
raw = (out / "host-native-receipt.json").read_bytes()
receipt = json.loads(raw)
assert receipt["head"] == "3b7af5096198ae9453b5616bc124def18798911c" and receipt["passed"]
assert receipt["sourceAllHashesUnchanged"] and receipt["allProcessesReaped"]
assert len(receipt["commands"]) == 6
for row in receipt["commands"]:
    data = (out / row["log"]).read_bytes()
    assert row["returncode"] == 0 and row["stopReason"] is None and row["originalProcessReaped"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
source = json.loads((out / "source-receipt.json").read_bytes())
assert source["fileCount"] == len(source["files"]) == 57
for row in source["files"]:
    data = (out / "source" / row["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
transport = (out / "host-step-3.log").read_text(encoding="utf8")
semantic = (out / "host-step-6.log").read_text(encoding="utf8")
assert "PASS SharedVectors: 61 authoritative protobuf cases" in transport
assert "PASS .NET native transport: 569 checks" in transport
assert "shared profile vectors: 77" in semantic and "shared profile lifetime/recovery: passed" in semantic
proof = dict(head=receipt["head"], receiptSha256=hashlib.sha256(raw).hexdigest(),
    allSixOriginalCommandsPass=True, capturedFilesUnchanged=57, actualProtobufCases=61,
    actualNamedTransportScenarios=13, actualNativeTransportChecks=569, actualSemanticRecords=77,
    original180SecondCommands900SecondCampaignPreserved=True, allProcessesReaped=True,
    environment=receipt["environment"], authoritativeLinuxQualification=False, fullCI=False)
(coord / "integration-v12-union-review/pr823-actual-dotnet-host-qualified-proof-v16.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf8")
print(json.dumps(proof))

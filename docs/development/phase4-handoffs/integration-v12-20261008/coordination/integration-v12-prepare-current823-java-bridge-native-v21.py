import json
from pathlib import Path

coord = Path(__file__).resolve().parent
old_job = "portable-v2-pr800-java-witness-floor-native-20261008-v149"
job = "integration-v12-current823-java-bridge-native-v21"
steps = json.loads((coord / "portable-v2-pr800-java-witness-floor-native-steps-v149.json").read_bytes())
steps = [[value.replace(old_job, job) for value in argv] for argv in steps]
path = coord / "integration-v12-current823-java-bridge-native-steps-v21.json"
path.write_text(json.dumps(steps, indent=2) + "\n", encoding="utf8")
source = (coord / "portable-v2-pr800-java-witness-floor-native-controller-v149.py").read_text(encoding="utf8")
source = source.replace(old_job, job)
path = coord / "integration-v12-current823-java-bridge-native-controller-v21.py"
compile(source, str(path), "exec")
path.write_text(source, encoding="utf8", newline="\n")
print(json.dumps(dict(head="76307dbbe24b51fb8b1316c4fbf7047914759a51", originalThreeCommandsRetained=True,
    originalGradle540AndController1800Retained=True, ownProjectCacheOutputOnly=True,
    actualJavaCaseCount60PlusOneContradictoryRefusalPreserved=True,
    actualExecutionPending=True, heldForSafeHostDiskMargin=True)))

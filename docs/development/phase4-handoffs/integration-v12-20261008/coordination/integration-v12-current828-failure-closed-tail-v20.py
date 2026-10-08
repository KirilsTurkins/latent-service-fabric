import json
from pathlib import Path

coord = Path(__file__).resolve().parent
raw = (coord / "integration-v12-current828-failed-go-ci-v20/job.log").read_text(encoding="utf8")
rows = []
needles = ("FAILED", "ValueError", "RuntimeError", "qualification failed", "error[E", "sdk-runtime-tests", "##[error]")
for index, line in enumerate(raw.splitlines(), 1):
    if not any(needle in line for needle in needles):
        continue
    text = line.split(" ", 1)[-1]
    if text.startswith("{"):
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if isinstance(value, dict):
            commands = value.get("commands")
            rows.append(dict(line=index, schemaVersion=value.get("schemaVersion"), status=value.get("status"),
                commandSteps=[dict(stage=row.get("stage"),exitCode=row.get("exitCode")) for row in commands] if isinstance(commands,list) else None))
            continue
    if len(text) <= 512:
        rows.append(dict(line=index,text=text))
print(json.dumps(rows,indent=2))

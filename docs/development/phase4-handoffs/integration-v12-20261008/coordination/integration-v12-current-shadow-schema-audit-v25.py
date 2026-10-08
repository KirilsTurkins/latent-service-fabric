from pathlib import Path
import hashlib
import json
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r'C:\Users\turkins\Desktop\latent-fabric')
heads = {'823': '76307dbbe24b51fb8b1316c4fbf7047914759a51',
         '828': '756a492b1678dec5e4f69dac11c571acc3836dd1',
         '811': '335dca010d299e554a4ab351e9fb525ae15e8d5c',
         '808': '1e129ef0ed6682c998f81a498e76bd4de61c6fec'}
paths = ['api/proto/buf.yaml', 'api/proto/buf.lock', 'tools/validate_phase1_descriptor.py']
listing = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', heads['808'], 'api/proto'], cwd=repo, text=True)
paths += [p for p in listing.splitlines() if p.endswith('.proto')]
records = {}
for name, head in heads.items():
    records[name] = {}
    for path in paths:
        result = subprocess.run(['git', 'show', head + ':' + path], cwd=repo, capture_output=True)
        records[name][path] = hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None
result = dict(heads=heads, records=records,
    identical808And811AllProtoAndConfig=records['808'] == records['811'],
    different808And823Paths=[p for p in paths if records['808'][p] != records['823'][p]],
    different808And828Paths=[p for p in paths if records['808'][p] != records['828'][p]],
    actualDescriptorGeneration=False)
out = coord / 'integration-v12-union-review/current-shadow-schema-input-audit-v25.json'
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'records'}))

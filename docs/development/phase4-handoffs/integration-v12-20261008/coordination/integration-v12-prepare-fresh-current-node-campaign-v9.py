"""Prepare only; actual freshly compiled capture digests are required to launch."""
from pathlib import Path
import json

coord=Path(__file__).resolve().parent
head='dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9'
steps=json.loads((coord/'integration-v12-union-review/observed-startup-source-paired-node-steps-v8.json').read_text())
steps=[list(row) for row in steps]
execution=steps[-1]
for index,part in enumerate(execution):
    execution[index]=part.replace('real-node-v8','real-node-v9').replace(
        '2c441d83f2706c402c167bedfa2d4dfb042faca7',head).replace(
        'six-captures-v2','six-captures-v3').replace('six-selected-v1','six-selected-v3')
digest_index=execution.index('--current-selections-digest')+1
execution[digest_index]='REQUIRES_ACTUAL_NEW_COMPILER_CAPTURE_DIGEST'
(coord/'integration-v12-union-review/fresh-current-node-steps-v9-preparation.json').write_text(json.dumps(steps,indent=2)+'\n')
print(json.dumps({'head':head,'actualFreshCompilerReceiptRequired':True,
                  'actualNewSelectionDigestRequired':True,'executableLaunchPrepared':False}))

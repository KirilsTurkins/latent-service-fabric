from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess

coord = Path(__file__).resolve().parent
repo = Path(r'C:\Users\turkins\Desktop\latent-fabric')
heads = {
    823: '76307dbbe24b51fb8b1316c4fbf7047914759a51',
    828: '756a492b1678dec5e4f69dac11c571acc3836dd1',
    808: '1e129ef0ed6682c998f81a498e76bd4de61c6fec',
    825: '601038c2b908144dadd11bcb48ddbab51606b5d4',
    811: '335dca010d299e554a4ab351e9fb525ae15e8d5c',
    800: '5d41e9b481e78818db4ac2a8ff30095301e61f94',
    790: '9977333b18c3990e52b5aebb7e0382a26dfa35aa',
    796: '8f85a60021786138a25f75b8fbc22c32f8789844',
    787: '4ce4eb63a04cded8bbb4b875c1b6863a3cc84678',
}
rows = []
for number, head in heads.items():
    def read(path):
        return subprocess.check_output(['git', 'show', head + ':' + path], cwd=repo)
    raw = read('api/proto/phase1-descriptor-contract.json')
    descriptor = json.loads(raw)
    files = {f['name']: f for f in descriptor['file']}
    node = files['latent/control/v1/node.proto']
    state = files['latent/control/v1/state.proto']
    node_messages = {m['name']: m for m in node.get('messageType', [])}
    state_messages = {m['name']: m for m in state.get('messageType', [])}
    def fields(message):
        return {f['name']: f['number'] for f in message.get('field', [])}
    witness = node_messages.get('TransactionStagingWitness')
    tree = fields(node_messages['ActivationTreeNode'])
    inspection = fields(state_messages['NamespaceInspection'])
    node_source = read('api/proto/latent/control/v1/node.proto')
    state_source = read('api/proto/latent/control/v1/state.proto')
    rows.append(dict(number=number, head=head,
        descriptorSha256=hashlib.sha256(raw).hexdigest(),
        sourceWitness=b'message TransactionStagingWitness' in node_source,
        descriptorWitnessFields=fields(witness) if witness else None,
        sourceTreeStaging=b'transaction_staging = 15;' in node_source,
        descriptorTreeStaging=tree.get('transaction_staging'),
        sourcePolicy=b'policy_digest = 12;' in state_source,
        descriptorPolicy=inspection.get('policy_digest'),
        descriptorSeamMatchesSource=(
            (bool(witness) == (b'message TransactionStagingWitness' in node_source))
            and ((tree.get('transaction_staging') == 15) == (b'transaction_staging = 15;' in node_source))
            and ((inspection.get('policy_digest') == 12) == (b'policy_digest = 12;' in state_source))),
        actualBufValidationPerformed=False))
out = coord / 'integration-v12-union-review' / 'current-descriptor-seam-audit-v24.json'
out.write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), rows=rows), indent=2) + '\n')
print(json.dumps(dict(custody=str(out), rows=rows)))

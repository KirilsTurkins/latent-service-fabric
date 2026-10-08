"""Run the installed protected diagnostic on one retained failed private node."""
from pathlib import Path
import json
import os
import sys

sys.path.insert(0,str(Path.cwd()))
from tools.build_process import run_bounded_result

base=Path('/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data')
failed=base/'jobs/integration-v12-current-java-real-node-v7/campaign'
output=base/'jobs/integration-v12-startup-diagnosis-actual-v3'
assert not output.exists()
output.mkdir(mode=0o700)
token=output/'operator-credential'
configuration=json.loads((failed/'node/bootstrap-node.json').read_text())
operators=[row for row in configuration['credentials'] if row['role']=='operator' and row['tenant']=='examples']
assert len(operators)==1
with token.open('xb') as handle: handle.write(operators[0]['token'].encode())
token.chmod(0o600)
result=run_bounded_result([str(base/'target/debug/examples/transaction_startup_diagnosis'),
    '--config',str(failed/'node/bootstrap-node.json'),'--credential-file',str(token),'--tenant','examples'],
    cwd=failed/'node',env=dict(os.environ),timeout_seconds=120,max_output_bytes=262144)
(output/'stdout.json').write_bytes(result.stdout)
(output/'stderr.txt').write_bytes(result.stderr)
assert result.returncode==0, 'actual diagnostic helper failed'
report=json.loads(result.stdout)
assert report['schemaVersion']=='latent.startup-failure-observation.v1'
print(json.dumps({'diagnosticHead':'f7e712728cd89215a8d3f60cff2f0323789dac51',
    'originalCampaignHead':'291f6f13da92aa675b5caa955b26e2c27f395d05',
    'report':report,'businessMutationsRetried':False,'guestInvoked':False}))

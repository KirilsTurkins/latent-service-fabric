"""Complete owned smoke03 cleanup; original completed workload/error stay intact."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))
from tools.artifact_identity_runner.files import reference, retain, write_json
from tools.optimization_docker.engine import Engine
from tools.optimization_docker.owned import stamp
from tools.optimization_evidence.common import canonical, read_json, require
from tools.optimization_kubernetes.collect import Campaign
from tools.optimization_kubernetes.transport import Journal, Kubernetes, Worker, private_tls
from tools.optimization_revision_runner.build import source

base = Path('/bench/kubernetes/lsf-112-8c22b65b1529')
original, root = base/'smoke-03', base/'smoke-03-recovery-01'
require(not root.exists(), 'fresh-cleanup-completion-root')
suite = read_json(original/'suite.json', 16*1024**2)
require(suite['failure'] is None and suite['source_after'] == suite['source']
        and suite['source']['commit'] == '2f7e3b1616056ba11a7e97ac613cdc3f416eb8c0'
        and len(suite['groups']) == 6 and len(suite['clients']) == 1
        and suite['cleanup']['namespace_absent'] is True and suite['cleanup']['remaining_pods'] == {}
        and suite['cleanup']['private_tls_removed'] is True and len(suite['cleanup']['pods']) == 45
        and suite['cleanup']['errors'] == [{'stage':'owned-resources','type':'EvidenceError',
                                          'reason':'kubernetes-worker-exec-stderr'}], 'original-cleanup-binding')
require(read_json(original/'cleanup.json') == suite['cleanup'], 'original-cleanup-sidecar')
root.mkdir()
(root/'transfers').mkdir()
record = {'schema':'latent.optimization.kubernetes-cleanup-completion.v1', 'source':source(Path.cwd()),
          'original_suite':reference(original/'suite.json',base),
          'original_cleanup':reference(original/'cleanup.json',base),
          'original_deleted_pods':suite['cleanup']['pods'], 'owner':suite['owner'], 'run_id':suite['run_id'],
          'started_nanos':stamp(), 'failure':None, 'status':'incomplete', 'new_guest_invokes':0}
record['helper'] = retain(Path(__file__), root/'recovery.py',root)
require(record['source'] == suite['source'], 'cleanup-completion-source')
recovery = Campaign.__new__(Campaign)
recovery.root, recovery.bootstrap_path = root, base/'bootstrap.json'
recovery.owner, recovery.run_id, recovery.namespace = (suite[key] for key in ('owner','run_id','namespace'))
recovery.namespace_uid = suite['namespace_uid']
recovery.namespace_attempted = recovery.remote_attempted = True
recovery.remote_root = '/var/local/lsf112/' + recovery.owner + '/' + recovery.run_id
recovery.sessions, recovery.pods, recovery.pending_pods = [], {}, set()
# These call references still belong to the original journal, as explicitly recorded above.
recovery.delete_receipts = suite['cleanup']['pods']
recovery.preparations, recovery.transfers = suite['preparations'], []
recovery.journal = Journal(root/'api.ndjson')
recovery.engine = Engine()
boot = read_json(base/'bootstrap.json')
recovery.worker = Worker(recovery.engine, boot['nodes']['worker']['container_id'], recovery.owner, recovery.journal)
recovery.private_directory = base/'private'/('tls-' + recovery.run_id)
require(not recovery.private_directory.exists(), 'original-private-tls-was-removed')
recovery.api = Kubernetes(recovery.owner+'-control-plane', private_tls(base/'private/kubeconfig',recovery.private_directory),recovery.journal)
try:
    record['cleanup'] = recovery.cleanup(failed=False)
    require(not record['cleanup']['errors'] and record['cleanup']['remote_removed'], 'cleanup-completion-incomplete')
    require(source(Path.cwd()) == record['source'] and reference(original/'suite.json',base) == record['original_suite']
            and reference(original/'cleanup.json',base) == record['original_cleanup'], 'cleanup-completion-originals-changed')
    record['status'] = 'owned-cleanup-completed'
except BaseException as error:
    record['failure'] = {'type':type(error).__name__,'reason':str(error)}
    raise
finally:
    record['finished_nanos'] = stamp()
    write_json(root/'recovery.json',record)
print(canonical({'status':record['status'],'new_guest_invokes':0,'output':str(root)}).decode())

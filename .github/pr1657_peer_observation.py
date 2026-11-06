from pathlib import Path, PurePosixPath
import hashlib, io, json, os, re, sys, tarfile, zipfile
sys.path.insert(0, str(Path.cwd()))
from tools import rust_thread_http_combined_node as controller
from tools.phase2_operator_process import write_json
root=Path(os.environ['RUNNER_TEMP'])
archive=root/'original.zip'
assert archive.stat().st_size == 78220087
assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'ae566867ca7ce84952c729c4eac6370fbf6f91659ad8c58de4f68e9790596dd9'
output=root/'peer-observation'; output.mkdir()
inputs=root/'retained-inputs'; inputs.mkdir()
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    expected=json.loads(z.read('rust-combined-root/native-products.json'))
    products={item['path']:item for item in expected}
    with tarfile.open(fileobj=io.BytesIO(z.read('rust-combined-root/native-products.tar.gz')), mode='r:gz') as t:
        assert {item.name for item in t.getmembers()} == set(products)
        for item in t.getmembers():
            assert item.isfile() and item.size == products[item.name]['bytes']
            data=t.extractfile(item).read(); assert hashlib.sha256(data).hexdigest()==products[item.name]['sha256']
            path=inputs/item.name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data);path.chmod(0o700)
    for name in z.namelist():
        prefix='rust-combined-signed/package/'
        if name.startswith(prefix):
            relative=PurePosixPath(name[len(prefix):]); assert not relative.is_absolute() and '..' not in relative.parts
            info=z.getinfo(name); assert info.file_size <= 4*1024*1024
            path=inputs/'package'/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(z.read(info))
write_json(output/'provenance.json', {'diagnosticOnly':True, 'nativeSourceCommit':'07ea89ccef37d03a11301cfdaeda5d5b5c00271d', 'nativeSourcePatchRetainedInArtifact':13523774023, 'nativeProducts':expected, 'originalGuestBudgetChanged':False})
native={name:inputs/path for name,path in {'latent':'latent','latentd':'latentd','package':'examples/package','capsule_contracts':'examples/capsule_contracts','capsule_authoring':'examples/capsule_authoring'}.items()}
original_configure=controller.configure
original_invoke=controller.invoke
def configure(*args):
    path=original_configure(*args); value=json.loads(path.read_bytes())
    value['providers']['activationRuntime']['limits']['nativeOwners']=12
    path.write_text(json.dumps(value)+'\n'); return path

def invoke(client,node,target,peer,probe,out,digest):
    try:
        return original_invoke(client,node,target,peer,probe,out,digest)
    finally:
        node.drain()
        write_json(out/'terminal-peer.json', peer.observation())
        markers=[line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                 if re.fullmatch(rb'LSF-COMBINED-(?:ROOT:[0-9]{1,4}:[0-9]{1,3}|PRESSURE:[0-9]{1,2}:[0-9]{1,4}:[0-9]{1,4})',line)]
        write_json(out/'native-pressure.json', {'markers':markers[:64], 'rawErrorTextRetained':False})
controller.configure=configure
controller.invoke=invoke
controller.run(inputs/'package',native,output/'node')

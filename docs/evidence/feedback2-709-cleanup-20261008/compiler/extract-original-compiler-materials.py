from pathlib import Path
import hashlib,json,os,stat,sys,tarfile,time
work=Path('/work/java709-four-fresh-37b48cd8-r2')
original=work/'original761-owner';original.mkdir(mode=0o700)
archive=Path('/inputs/original761-tool-extraction-owner.tar')
assert os.geteuid()==23001 and sys.version_info[:3]==(3,13,5)
raw=archive.read_bytes();assert len(raw)==21575680 and hashlib.sha256(raw).hexdigest()=='1827a28e738243157b2bcb9939aa6254b7ed44b2e800f90796bced26d287f6d8'
with tarfile.open(archive) as source:
    members=source.getmembers();assert len(members)<=8192
    assert all(x.isdir() or x.isfile() for x in members)
    assert all(not x.name.startswith('/') and '..' not in Path(x.name).parts for x in members)
    source.extractall(original,filter='data')
sys.path.insert(0,str(original))
from tools.dev_workflow import bundle,tool_inventory
from tools.dev_workflow.common import decode
from tools.dev_managed_tools import unpack
from tools.java_guest.compiler import tool_inventory as compiler_inventory
start=time.monotonic()
def check():assert time.monotonic()-start<300,'original producer material extraction deadline exceeded'
def identity(path):
    info=path.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not path.is_symlink()
    raw=path.read_bytes();return {'bytes':len(raw),'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}
PRODUCER='761172002e4a4d02102f8c757235b888fe4859e1'
ARCHIVE='sha256:37e7225616c22665f39b2c50348be402cafb5cf087189eac77bef73ed70721c9'
POLICY='sha256:ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba'
copies=json.loads(Path('/controller/original-tool-input-copy-verification.json').read_bytes())
for name,row in copies['files'].items():assert identity(Path('/bundle')/name)==row
auth_raw=Path('/bundle/verification-receipt.json').read_bytes();tracked=Path('/controller/historical-tool-verification-receipt.git.json').read_bytes();association=json.loads(Path('/controller/historical-tool-auth-association.json').read_bytes())
assert hashlib.sha256(tracked).hexdigest()==association['historicalTrackedSha256'] and auth_raw.replace(b'\r\n',b'\n')==tracked
auth=json.loads(auth_raw);assert auth['attestationExitCode']==0 and auth['producerSourceCommit']==PRODUCER and auth['policyInputDigest']==POLICY
descriptor=bundle.manifest(decode(Path('/bundle/developer-bundle.json').read_bytes(),bundle.MAX_MANIFEST),target='linux-x86_64',version='0.1.0-alpha.5',commit=PRODUCER)
assert descriptor['archive']['sha256']==ARCHIVE==auth['archiveSha256']
bundle.extract(Path('/bundle'),descriptor,work/'bundle',check=check);bundle.verify_cache(work/'bundle',descriptor,check=check)
tools=tool_inventory.validate(decode((work/'bundle/guest-tools.json').read_bytes(),tool_inventory.MAX_DOCUMENT),'java',548,'linux-x86_64');assert tools['sourceCommit']==PRODUCER
unpack(work/'bundle/sdk',work/'managed',check)
roots={name:work/'managed'/name for name in ('jdk','gradle','wasi-sdk')};closure=compiler_inventory(roots)
assert len(closure)==2902802 and hashlib.sha256(closure).hexdigest()=='46190f6e208fc5a0046522f2783adcc0752a7bc762db7a8b507e198fd064883b'
record={'schemaVersion':'latent.original-compiler-material-owner-handoff.v1','originalProducer':PRODUCER,'producerOwnerTree':'52504b41ca1d5405d37f0f401f1b47adb1142118','producerOwnerArchiveSha256':'1827a28e738243157b2bcb9939aa6254b7ed44b2e800f90796bced26d287f6d8','originalToolArchive':ARCHIVE,'historicalCompilerRoleReceiptVerified':True,'originalHostAbi':descriptor['hostAbi'],'originalGuestToolInventory':tools['identity'],'originalCompilerClosureBytes':len(closure),'originalCompilerClosureSha256':'sha256:'+hashlib.sha256(closure).hexdigest(),'originalAbiGuardUnchanged':True,'currentAbiGuardUnchanged':True,'originalBundleInstalledAsCurrentProfile':False,'runtimeAuthorityGranted':False,'signingOperations':0,'diagnosticClockStarted':False,'thirdPartyCompilerMaterialPaths':{name:str(path) for name,path in roots.items()}}
Path('/output/original-compiler-material-owner-handoff.json').write_text(json.dumps(record,indent=2)+'\n')
print('Original producer-owned extractor reverified the unchanged third-party compiler closure; no current installed-profile acceptance or runtime authority',flush=True)

"""Owned compiler-only campaign using the authenticated developer761 tool bundle."""
from pathlib import Path
import hashlib,json,os,sys,time
sys.path.insert(0,'/recipe')
from tools.dev_workflow import bundle,tool_inventory
from tools.dev_workflow.common import decode
from tools.dev_managed_tools import unpack
from tools.build_process import run_bounded_result

SOURCE='1f8944ca0ee9a4b65a3f3a51696349b21ee31647'
PRODUCER='761172002e4a4d02102f8c757235b888fe4859e1'
STORE=Path('/store')
START=time.monotonic()
REPORT={'schemaVersion':1,'evidenceKind':'authored-component-compiler','compilerSource':SOURCE,
        'toolProducerSource':PRODUCER,'compiled':False,'signedNodeExecutionQualified':False,
        'admissionRejectionQualified':False,'steps':[]}

def check():
    if time.monotonic()-START>6000:
        raise RuntimeError('owned Java compiler campaign deadline exceeded')

def save():
    (STORE/'controller-receipt.json').write_text(json.dumps(REPORT,indent=2)+'\n')

def run(stage,argv,cwd=STORE,timeout=600,maximum=4*1024*1024,env=None):
    check()
    if env is None:
        env=dict(os.environ)
    result=run_bounded_result(argv,cwd,env,timeout_seconds=min(timeout,6000-(time.monotonic()-START)),max_output_bytes=maximum)
    for label,value in (('stdout',result.stdout),('stderr',result.stderr)):
        (STORE/(stage+'.'+label+'.log')).write_bytes(value)
    REPORT['steps'].append({'stage':stage,'command':argv,'exitCode':result.returncode})
    save()
    if result.returncode:
        raise RuntimeError('owned compiler stage failed:'+stage)
    return result.stdout

try:
    auth=json.loads(Path('/bundle/verification-receipt.json').read_text())
    assert auth['attestationExitCode']==0 and auth['policyInputDigest']=='sha256:ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba'
    assert auth['producerSourceCommit']==PRODUCER
    descriptor=bundle.manifest(decode(Path('/bundle/developer-bundle.json').read_bytes(),bundle.MAX_MANIFEST),target='linux-x86_64',version='0.1.0-alpha.5',commit=PRODUCER)
    assert descriptor['archive']['sha256']==auth['archiveSha256']
    bundle.extract(Path('/bundle'),descriptor,STORE/'bundle',check=check)
    inventory=tool_inventory.validate(decode((STORE/'bundle/guest-tools.json').read_bytes(),tool_inventory.MAX_DOCUMENT),'java',548,'linux-x86_64',host_abi=descriptor['hostAbi'])
    assert inventory['sourceCommit']==PRODUCER
    unpack(STORE/'bundle/sdk',STORE/'managed',check)
    REPORT['toolBundleArchiveDigest']=auth['archiveSha256']
    REPORT['guestToolInventoryDigest']=inventory['identity']
    REPORT['managedToolInventoryDigest']=json.loads((STORE/'bundle/sdk/managed-inputs.json').read_text())['identity']
    REPORT['toolBundleHostAbi']=descriptor['hostAbi']
    save()
    git=run('git-version',['git','--version'],maximum=16384).decode().strip()
    REPORT['gitVersion']=git
    run('source-clone',['git','clone','--depth','1','--branch','feat/feedback2-java-transactions-718','https://github.com/KirilsTurkins/latent-service-fabric.git',str(STORE/'source')],timeout=300)
    observed=run('source-revision',['git','-C',str(STORE/'source'),'rev-parse','HEAD'],maximum=16384).decode().strip()
    assert observed==SOURCE, 'published compiler source changed'
    assert not run('source-status',['git','-C',str(STORE/'source'),'status','--porcelain','--untracked-files=normal'],maximum=65536)
    env=dict(os.environ)
    env['PATH']=str(STORE/'bundle/sdk/bin')+':'+str(STORE/'managed/jdk/bin')+':'+str(STORE/'managed/gradle/bin')+':'+env['PATH']
    env['JAVA_HOME']=str(STORE/'managed/jdk')
    env['PYTHONUTF8']='1'
    env['PYTHONDONTWRITEBYTECODE']='1'
    run('compile-transaction-guests',['/usr/local/bin/python3','-B',str(STORE/'source/tools/compile_transaction_guests.py'),'--language','java','--wasi-sdk',str(STORE/'managed/wasi-sdk'),'--java-schema-put-once','--output',str(STORE/'components-r1')],cwd=STORE/'source',timeout=4800,maximum=16*1024*1024,env=env)
    REPORT['variants']={}
    for path in sorted((STORE/'components-r1').glob('*/report.json')):
        value=json.loads(path.read_text())
        assert value['compiled'] and not value['signedNodeExecutionQualified'] and not value['admissionRejectionQualified']
        REPORT['variants'][value['variant']]={k:value[k] for k in ('componentDigest','componentBytes','companionDigest','sourceDigest','sourceArchiveDigest','sourceRevision')}
    assert len(REPORT['variants'])==5
    REPORT['compiled']=True
except BaseException as error:
    REPORT['failedReason']=str(error)
    raise
finally:
    REPORT['seconds']=round(time.monotonic()-START,6)
    save()

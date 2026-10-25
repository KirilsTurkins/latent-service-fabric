"""Qualification-private generated-CIL reference; no NativeAOT or native build."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None,''}:
    sys.path.insert(0,str(ROOT))
from tools.build_process import BuildProcessError, run_bounded_result

BASE = '655199b641fd7c35facc8531af26714095d44790'
TOOL = 'sdk/dotnet-guest/tools/http-errors'
FIXTURE = 'tools/fixtures/dotnet-aggregate-wait-reference'
CORE_MEMBER = 'runtimes/wasi-wasm/native-hidden/System.Private.CoreLib.dll'
CORE_SHA = '29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735'
CECIL_MEMBER = 'tools/net/Mono.Cecil.dll'
CECIL_SHA = '2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7'
CASES = (
    'entry-cancellation-before-set', 'disposal-before-cancellation', 'zero-and-already-set-no-clock',
    'all-seven-public-overloads', 'original-validation-precedence', 'pending-first-order',
    'pending-reverse-order', 'original-multiple-fault-identity', 'original-task-cancellation-token',
    'single-overall-deadline', 'late-completion-before-cancellation', 'later-cancellation-detaches-original',
    'ready-ignores-completed-old-main', 'ready-after-countdown-before-poll',
    'nested-single-inside-aggregate', 'nested-aggregate-inside-single', 'dispatch-fault-restores-state',
    'late-context-restoration-keeps-timeout', 'late-restoration-nested-decision',
    'wake-admission-refusal-restores-state', 'cleanup-cancel-refusal-restores-state',
    'cleanup-dispose-refusal-restores-state', 'non-wasi-original-entry-once',
)
MAX_CHANNEL = 4 * 1024**2
MAX_PACKAGE = 512 * 1024**2
MAX_PUBLIC = 256 * 1024**2
MAX_DOCUMENT = 1024**2
CASE_KEYS = {'control','passed','scope','sourceQualified','nativeAotExecuted','signedComponentExecuted',
    'wholeWaitAllCoreGuestQualified','runtime','runtimeVersion','hostCoreLibSha256',
    'originalTargetStateRestored','startClockReads','remainingClockReads','wakeCalls',
    'copiedValidationCalls','dispatches','linkedSources','cancels','disposals','cil'}
COUNTERS = ('startClockReads','remainingClockReads','wakeCalls','copiedValidationCalls',
            'dispatches','linkedSources','cancels','disposals')
PORTS = {'IsWasi','CopiedDisposed','StartClock','RemainingClock','Dispatch','EnsureReady',
         'Delay','AggregateBridge','SingleBridge'}
ORIGINALS = (
    (0x06003e7f,46,'87d5707683590051481de68a5c41d27654e0223f72d9d826950aa6bded0015fa'),
    (0x06003e80,31,'3230751c809caea2191f78d05b867d24c6d54fc334e66ab2aae202af25d09355'),
    (0x06003e81,85,'01319d2a08ba4ae07b1e5c364d0b4fd338471aa848c34777c235a4e90c5b571e'),
    (0x06003e82,45,'5968cd2411bfc34c2ecd8ef2211d03618cfbfe40c12ff05d72b6e8f8f45524b0'),
    (0x06003e83,38,'dce230be52341bd676be3317c7898112d7795f4570f647eef7a2e4b4a50a4935'),
    (0x06003e84,37,'6343973682f40d3769ee6c682104d4cb968b473be63720a76cf5bd24511220c0'),
    (0x06003e85,84,'4964812ad96bbf22498f0b6aa72665266aab885ac8281a13244699fdcd49201a'),
    (0x06003e86,471,'244c14ca727b59a6291824b90984aa76c49bf5e091cf8bc00a8e10a187f4bb6d'),
    (0x06003e88,149,'2b0fb5a58f02b0341e2b94dbcb1460307e1e7b256f994f4b0956bfcfa1bb6d00'),
)
REFERENCE_PROJECT = ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
    '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
    '<Nullable>enable</Nullable><UseSharedCompilation>false</UseSharedCompilation></PropertyGroup>'
    '<ItemGroup><Reference Include="Mono.Cecil" HintPath="$(LsfCecilPath)" /></ItemGroup></Project>')
RECIPE = (
    'tools/run_dotnet_aggregate_wait_reference.py',
    'tools/build_process.py','tools/build_process_linux.py','tools/build_process_signals.py',
    'tools/fixtures/dotnet-aggregate-wait-reference/ActualCil.cs',
    'tools/fixtures/dotnet-aggregate-wait-reference/Ports.cs',
    'tools/fixtures/dotnet-aggregate-wait-reference/Program.cs',
    'sdk/dotnet-guest/global.json','sdk/dotnet-guest/nuget.config',
    'sdk/dotnet-guest/probes/smoke/packages.lock.json',
    'sdk/dotnet-guest/tools/package-hash/Program.cs',
    'sdk/dotnet-guest/tools/package-hash/PackageHash.csproj',
    '.github/workflows/dotnet-aggregate-wait-reference.yml',
)
COMMAND_NAMES = (
    'dotnet-version','dotnet-info','dotnet-runtimes','source-head','source-tree','clean-source',
    'package-hash-build','integrity-runtime.wasi-wasm.microsoft.dotnet.ilcompiler.llvm',
    'integrity-microsoft.net.illink.tasks','baseline-source-list','baseline-tool-build','candidate-tool-build',
    'aggregate-derivation','reference-build','final-clean-source',
    *(variant+'-'+mode for variant in ('baseline','candidate')
      for mode in ('task-wait','finite-task-wait','managed-task-wait')),
    *('baseline-source-'+str(number) for number in range(64)),
    *('case-'+name for name in CASES),
)
PHASES = ('preflight','normal-nuget-integrity','build-two-source-exact-tools','old-mode-exact-equality',
    'candidate-derivation','build-host-reference','generated-il-reference-cases','final-input-rechecks')

def need(value, code):
    if not value:
        raise ValueError(code)

def identity(raw):
    return {'bytes':len(raw), 'sha256':'sha256:'+hashlib.sha256(raw).hexdigest()}

def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()
    need(len(raw) <= MAX_DOCUMENT, 'reference-document-limit')
    path.write_bytes(raw)

def bounded(path, maximum):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size<=maximum,'reference-file-bound')
    with path.open('rb') as stream:
        raw=stream.read(maximum+1)
    need(len(raw)<=maximum,'reference-file-bound')
    return raw

def file_identity(path, maximum):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size<=maximum,'reference-file-bound')
    digest=hashlib.sha256();count=0
    with path.open('rb') as stream:
        while raw:=stream.read(1024**2):
            count+=len(raw);need(count<=maximum,'reference-file-bound');digest.update(raw)
    return {'bytes':count,'sha256':'sha256:'+digest.hexdigest()}

def hexadecimal(value, prefix=''):
    return isinstance(value,str) and re.fullmatch(re.escape(prefix)+r'[0-9a-f]{64}',value) is not None

def candidate_shape(selected, assembly):
    need(isinstance(selected,dict) and selected.get('generatedHelperCount')==95
        and type(selected['generatedHelperCount']) is int
        and selected.get('unchangedOriginalMethods')==44710
        and type(selected['unchangedOriginalMethods']) is int
        and selected.get('maximumNestedWaits')==32
        and selected.get('sourceDigest')=='sha256:'+CORE_SHA
        and selected.get('cecilDigest')=='sha256:'+CECIL_SHA
        and selected.get('outputDigest')==identity(assembly)['sha256']
        and selected.get('defaultClientComponentQualified') is False
        and selected.get('completeOriginalWaitRemainderPreserved') is True,'reference-candidate-closed-shape')
    value=selected.get('aggregateTaskWait')
    need(isinstance(value,dict) and value.get('patch')=='latent.dotnet.wait-all.v1'
        and value.get('profile')=='dotnet-aggregate-task-wait-candidate-v1'
        and all(value.get(key) is False for key in ('qualificationComplete','productionSelected','limitsChanged')),
        'reference-candidate-profile')
    rows=value.get('originalMethods')
    need(isinstance(rows,list) and len(rows)==9,'reference-nine-preimages')
    for row,(token,size,digest) in zip(rows,ORIGINALS,strict=True):
        need(isinstance(row,dict) and set(row)=={'method','token','ilBytes','ilSha256'}
            and type(row['token']) is int and row['token']==token
            and type(row['ilBytes']) is int and row['ilBytes']==size
            and row['ilSha256']=='sha256:'+digest and isinstance(row['method'],str)
            and 0<len(row['method'])<512,'reference-preimage-identity')
    original_names={row['method'] for row in rows}
    for key,count in (('originalRemainders',9),('rewrittenBodies',15)):
        mapping=value.get(key)
        need(isinstance(mapping,dict) and len(mapping)==count
            and original_names<=set(mapping)
            and all(isinstance(name,str) and len(name)<512 and hexadecimal(digest)
                    for name,digest in mapping.items()),'reference-derived-identities')

def case_shape(value, name, selected):
    need(isinstance(value,dict) and set(value)==CASE_KEYS and value['control']==name
        and value['passed'] is True and value['originalTargetStateRestored'] is True
        and value['scope']=='actual-generated-IL-with-closed-host-reference-ports'
        and all(value[key] is False for key in ('sourceQualified','nativeAotExecuted',
            'signedComponentExecuted','wholeWaitAllCoreGuestQualified')),'reference-case-result')
    need(all(type(value[key]) is int and 0<=value[key]<=256 for key in COUNTERS)
        and hexadecimal(value['hostCoreLibSha256'])
        and isinstance(value['runtime'],str) and 0<len(value['runtime'])<256
        and isinstance(value['runtimeVersion'],str) and re.fullmatch(r'10\.0\.[0-9]+',value['runtimeVersion']),
        'reference-case-runtime-and-counters')
    observation=value['cil']
    need(isinstance(observation,dict) and set(observation)=={'copiedMethods','tokenMap',
        'originalInstructionsBranchesAndEhCopied','pinnedWasiCountdownClassExecuted',
        'hostPrivateCountdownCounterpart','nativeWasiPollAndLedgerQualified','runtimeAddressesRetained'}
        and observation['originalInstructionsBranchesAndEhCopied'] is True
        and observation['hostPrivateCountdownCounterpart'] is True
        and all(observation[key] is False for key in ('pinnedWasiCountdownClassExecuted',
            'nativeWasiPollAndLedgerQualified','runtimeAddressesRetained')),'reference-il-scope')
    methods=observation['copiedMethods'];need(isinstance(methods,list) and len(methods)==16,'reference-sixteen-copies')
    by_name={}
    for row in methods:
        need(isinstance(row,dict) and set(row)=={'method','ilSha256','normalizedBodySha256','locals','handlers'}
            and isinstance(row['method'],str) and len(row['method'])<512
            and hexadecimal(row['ilSha256']) and hexadecimal(row['normalizedBodySha256'])
            and isinstance(row['locals'],list) and len(row['locals'])<=32
            and all(isinstance(local,str) and len(local)<512 for local in row['locals'])
            and isinstance(row['handlers'],list) and len(row['handlers'])<=16,'reference-method-shape')
        need(row['method'] not in by_name,'reference-duplicate-method');by_name[row['method']]=row
        for handler in row['handlers']:
            need(isinstance(handler,dict) and set(handler)=={'kind','start','end','handlerStart','handlerEnd'}
                and handler['kind'] in ('Catch','Finally','Fault','Filter')
                and all(type(handler[key]) is int and 0<=handler[key]<65536
                        for key in ('start','end','handlerStart','handlerEnd'))
                and handler['start']<handler['end'] and handler['handlerStart']<handler['handlerEnd'],
                'reference-eh-shape')
    rewritten=selected['aggregateTaskWait']['rewrittenBodies']
    common=set(by_name)&set(rewritten)
    need(len(common)==14 and all(by_name[method]['normalizedBodySha256']==rewritten[method] for method in common),
        'reference-emitted-body-binding')
    extra=set(by_name)-common
    need(extra=={'System.Void System.Threading.WasiEventLoop::LsfDispatchUntilActualTaskCompletion(System.Object)',
        'System.Int32 System.Threading.TimeoutHelper::UpdateTimeOut(System.Int64,System.Int64)'},'reference-two-extra-copies')
    timeout=by_name['System.Int32 System.Threading.TimeoutHelper::UpdateTimeOut(System.Int64,System.Int64)']
    need(timeout['ilSha256']=='f3834985458c4d55a958c241f5bc3e6c4196473162b11e9b3a749a48213dc6d4',
        'reference-original-timeout-code')
    mapping=observation['tokenMap']
    need(isinstance(mapping,list) and 0<len(mapping)<=256 and mapping==sorted(set(mapping))
        and all(isinstance(row,str) and 0<len(row)<2048 and ' => ' in row for row in mapping),
        'reference-token-map-bound')
    ports={row.split(' => explicit-host-port:',1)[1] for row in mapping if ' => explicit-host-port:' in row}
    need(ports==PORTS,'reference-exact-port-map')
    # Every case also asserts its own semantic outcome in the source-bound CLR harness.
    # These checks independently reject altered result records and clock/cleanup regressions.
    infinite={'entry-cancellation-before-set','disposal-before-cancellation','zero-and-already-set-no-clock',
        'all-seven-public-overloads','original-validation-precedence','pending-first-order','pending-reverse-order',
        'original-multiple-fault-identity','original-task-cancellation-token','late-completion-before-cancellation',
        'later-cancellation-detaches-original','ready-ignores-completed-old-main','ready-after-countdown-before-poll',
        'nested-single-inside-aggregate','nested-aggregate-inside-single','non-wasi-original-entry-once'}
    if name in infinite:
        need(value['startClockReads']==0 and value['remainingClockReads']==0,'reference-infinite-clock-observation')
    else:
        need(value['startClockReads']==1 and value['wakeCalls']==1,'reference-one-finite-start')
    need(value['linkedSources']==value['cancels']==value['disposals'],'reference-owned-source-cleanup')
    return observation

class Commands:
    def __init__(self, scratch, public):
        self.scratch, self.public, self.started = scratch, public, time.monotonic()
        self.records = []
        self.cleanup_safe = True
        # No token, credential, startup-hook or MSBuild override environment is
        # forwarded to these trusted host tools or their retained diagnostics.
        self.environment = {key:os.environ[key] for key in ('PATH','DOTNET_ROOT','DOTNET_ROOT_X64') if key in os.environ}
        (scratch/'home').mkdir(mode=0o700)
        self.environment.update(HOME=str(scratch/'home'),LANG='C.UTF-8',LC_ALL='C.UTF-8',
            XDG_CONFIG_HOME=str(scratch/'home/.config'),XDG_CACHE_HOME=str(scratch/'home/.cache'))
        self.environment.update(DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1',
            DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE='true',
            DOTNET_CLI_HOME=str(scratch/'cli-home'), NUGET_PACKAGES=str(scratch/'nuget'),
            DOTNET_EnableDiagnostics='0', MSBUILDDISABLENODEREUSE='1',
            DOTNET_CLI_USE_MSBUILD_SERVER='0', TMPDIR=str(scratch/'tmp'))
        (scratch/'tmp').mkdir()
        (public/'commands').mkdir()

    def check(self):
        need(time.monotonic()-self.started < 600, 'reference-aggregate-deadline')

    def run(self, name, *argv, cwd=None):
        self.check()
        need(name in COMMAND_NAMES,'reference-command-name')
        need(name not in {row['name'] for row in self.records}, 'reference-duplicate-command')
        paths=[self.public/'commands'/(name+suffix) for suffix in ('.stdout','.stderr')]
        start=time.monotonic()
        record={'name':name,'argv':[str(arg) for arg in argv],'exitCode':None,
            'processOwner':'tools.build_process.run_bounded_result','processCleanup':'unconfirmed',
            'capture':'unavailable','failureReason':None,'cleanupReserveSeconds':5,
            'maximumWallSeconds':120,'maximumCombinedOutputBytes':MAX_CHANNEL}
        self.records.append(record)
        try:
            remaining=min(120,600-(time.monotonic()-self.started))
            need(remaining>5,'reference-command-cleanup-reserve')
            result=run_bounded_result(record['argv'],cwd=cwd or self.scratch,env=self.environment,
                timeout_seconds=remaining-5,max_output_bytes=MAX_CHANNEL)
        except BuildProcessError as error:
            record['failureReason']=error.reason
            if error.reason=='process-cleanup':self.cleanup_safe=False
            raise
        finally:
            record['seconds']=time.monotonic()-start
        # The maintained owner returns only after leader AND descendant cleanup.
        # Timeout/overflow/cleanup failures honestly have no retained raw capture.
        record.update(exitCode=result.returncode,processCleanup='confirmed',capture='complete',
            stdout=identity(result.stdout),stderr=identity(result.stderr))
        for path,raw in zip(paths,(result.stdout,result.stderr),strict=True):
            with path.open('xb') as stream:stream.write(raw)
        need(result.returncode == 0, 'reference-command-failed:'+name)
        return result.stdout

def fetch(url, target, commands):
    need(urllib.parse.urlsplit(url).scheme == 'https' and not target.exists(), 'reference-package-source')
    total=0
    with urllib.request.urlopen(url,timeout=30) as incoming,target.open('xb') as output:
        need(urllib.parse.urlsplit(incoming.url).scheme == 'https', 'reference-redirect-scheme')
        if incoming.headers.get('Content-Length'):
            need(int(incoming.headers['Content-Length'])<=MAX_PACKAGE,'reference-package-length')
        while raw:=incoming.read(1024*1024):
            commands.check();total+=len(raw)
            need(total<=MAX_PACKAGE,'reference-package-limit');output.write(raw)
    return file_identity(target,MAX_PACKAGE)

def selected_member(archive_path, name, maximum, digest):
    with zipfile.ZipFile(archive_path) as archive:
        rows=archive.infolist();need(len(rows)<=32768,'reference-package-index-limit')
        seen=set()
        for row in rows:
            parsed=PurePosixPath(row.filename);mode=row.external_attr>>16
            need(0<len(row.filename)<=1024 and not parsed.is_absolute() and '\\' not in row.filename
                and ':' not in row.filename and all(ord(char)>=32 for char in row.filename)
                and all(part not in ('','.','..') for part in row.filename.rstrip('/').split('/'))
                and not row.flag_bits&1 and stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR)
                and row.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED), 'reference-package-path-or-mode')
            key=row.filename.casefold().rstrip('/')
            need(key not in seen,'reference-package-alias');seen.add(key)
        matches=[row for row in rows if row.filename==name]
        need(len(matches)==1 and not matches[0].is_dir()
            and stat.S_IFMT(matches[0].external_attr>>16) in (0,stat.S_IFREG)
            and 0<matches[0].file_size<=maximum,'reference-selected-assembly-size')
        raw=archive.read(matches[0])
        need(hashlib.sha256(raw).hexdigest()==digest,'reference-selected-assembly-digest')
        return raw

def origin():
    result={}
    for key in ('GITHUB_WORKFLOW_REF','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_REF_NAME'):
        value=os.environ.get(key,'')
        need(0<len(value)<=512 and all(32<=ord(char)<127 for char in value),'reference-workflow-origin')
        result[key]=value
    need(result['GITHUB_RUN_ID'].isascii() and result['GITHUB_RUN_ID'].isdecimal()
        and result['GITHUB_RUN_ATTEMPT'].isascii() and result['GITHUB_RUN_ATTEMPT'].isdecimal()
        and re.fullmatch(r'[0-9a-f]{40}',result['GITHUB_SHA']) is not None
        and result['GITHUB_EVENT_NAME']=='push'
        and result['GITHUB_REF_NAME']=='feat/dotnet-waitall-source-20261025'
        and result['GITHUB_WORKFLOW_REF'].endswith('/.github/workflows/dotnet-aggregate-wait-reference.yml@refs/heads/'+result['GITHUB_REF_NAME']),
        'reference-fixed-workflow-origin')
    return result

def public_inventory(output, command_names):
    names={'WAITALL-REFERENCE.json':MAX_DOCUMENT,'candidate.json':MAX_DOCUMENT,'IL-MAP.json':MAX_DOCUMENT}
    names.update({'assemblies/'+name+'.dll':8*1024**2
                  for name in ('task-wait','finite-task-wait','managed-task-wait','aggregate')})
    names.update({'commands/'+name+suffix:MAX_CHANNEL
                  for name in command_names for suffix in ('.stdout','.stderr')})
    observed={}
    for number,path in enumerate(output.rglob('*')):
        need(number<len(names)+2,'reference-public-entry-limit')
        need(not path.is_symlink(),'reference-public-link')
        if path.is_dir():
            need(path.relative_to(output).as_posix() in ('commands','assemblies'),'reference-public-directory')
            continue
        key=path.relative_to(output).as_posix()
        need(key in names,'reference-public-allowlist')
        observed[key]=file_identity(path,names[key])
    need(sum(row['bytes'] for row in observed.values())<=MAX_PUBLIC,'reference-public-total-limit')
    return observed

def admit_evidence(output):
    """Independent always-run upload gate, never a qualification-result override."""
    output=Path(output).absolute()
    record=output.parent/'dotnet-aggregate-reference-admission.json'
    need(not record.exists() and not record.is_symlink(),'reference-fresh-admission-record')
    projection={'status':'unavailable','failedPhase':'unavailable','failureType':'unavailable'}
    result={'schemaVersion':'latent.dotnet.waitall.evidence-admission.v1','status':'failed',
        'scope':'bounded-public-retention-only','originalController':projection,'qualificationPromoted':False}
    try:
        need(sys.platform=='linux' and output.is_dir() and ROOT not in output.parents
            and output not in ROOT.parents
            and not any(path.is_symlink() for path in (output,*output.parents)),
            'reference-evidence-root')
        receipt_path=output/'WAITALL-REFERENCE.json'
        if receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.stat().st_size<=MAX_DOCUMENT:
            value=json.loads(bounded(receipt_path,MAX_DOCUMENT))
            if isinstance(value,dict) and value.get('schemaVersion')=='latent.dotnet.waitall.reference.v1':
                projection['status']=value.get('status') if value.get('status') in ('passed','failed') else 'unavailable'
                projection['failedPhase']=value.get('failedPhase') if value.get('failedPhase') in PHASES else 'unavailable'
                projection['failureType']=value.get('failureType') if value.get('failureType') in (
                    'ValueError','TypeError','KeyError','OSError','FileNotFoundError','TimeoutError',
                    'BuildProcessError','RuntimeError','KeyboardInterrupt','SystemExit','HTTPError','URLError') else 'unavailable'
                projection['receipt']=file_identity(receipt_path,MAX_DOCUMENT)
                if isinstance(value.get('sourceCommit'),str) and re.fullmatch(r'[0-9a-f]{40}',value['sourceCommit']):
                    projection['sourceCommit']=value['sourceCommit']
        need(projection['status'] in ('passed','failed'),'reference-controller-receipt-required')
        result['files']=public_inventory(output,COMMAND_NAMES)
        # Reserve the separate bounded admission JSON inside the SAME upload cap.
        need(sum(row['bytes'] for row in result['files'].values())<=MAX_PUBLIC-MAX_DOCUMENT,
            'reference-upload-union-limit')
        result['status']='passed'
    except (ValueError,TypeError,KeyError,OSError,RecursionError) as error:
        result['admissionFailureType']=type(error).__name__
    # This single bounded projection is the ONLY upload when the main gate fails.
    write_json(record,result)
    return result

def build(commands, name, project, output, cecil=None):
    args=['dotnet','build',project,'-c','Release','--output',output,
        '--artifacts-path',output.parent/(name+'-artifacts'),'-p:RestoreConfigFile='+str(commands.scratch/'clear.config'),
        '-p:NuGetAudit=false','-p:UseSharedCompilation=false','-nodeReuse:false',
        '-p:ImportDirectoryBuildProps=false','-p:ImportDirectoryBuildTargets=false']
    if cecil is not None:args.append('-p:LsfCecilPath='+str(cecil))
    commands.run(name,*args)

def qualify(output):
    need(sys.platform=='linux' and sys.version_info >= (3,13),'reference-linux-python313')
    output=Path(output).absolute()
    need(not output.exists() and ROOT not in output.parents and output not in ROOT.parents,'reference-fresh-external-output')
    output.mkdir(mode=0o700)
    scratch=Path(tempfile.mkdtemp(prefix='dotnet-waitall-reference-',dir=output.parent))
    commands=Commands(scratch,output)
    receipt={'schemaVersion':'latent.dotnet.waitall.reference.v1','status':'failed',
        'scope':'tool-only-generated-CIL-reference','sourceQualified':False,'nativeAotExecuted':False,
        'signedComponentExecuted':False,'productionSelected':False,'commands':commands.records,'cases':[],
        'processOwnerBoundary':'trusted-build-process-groups;session-escape-and-supervisor-SIGKILL-excluded'}
    phase='preflight'
    failure=None
    try:
        workflow=origin();receipt['workflowOrigin']=workflow
        (scratch/'global.json').write_bytes((ROOT/'sdk/dotnet-guest/global.json').read_bytes())
        (scratch/'clear.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>\n')
        need(commands.run('dotnet-version','dotnet','--version').strip()==b'10.0.100','reference-actual-sdk-version')
        commands.run('dotnet-info','dotnet','--info')
        commands.run('dotnet-runtimes','dotnet','--list-runtimes')
        head=commands.run('source-head','git','rev-parse','HEAD',cwd=ROOT).decode().strip()
        tree=commands.run('source-tree','git','rev-parse','HEAD^{tree}',cwd=ROOT).decode().strip()
        need(commands.run('clean-source','git','status','--porcelain',cwd=ROOT)==b'','reference-dirty-source')
        need(head==workflow['GITHUB_SHA'],'reference-workflow-source-mismatch')
        receipt.update(sourceCommit=head,sourceTree=tree,baselineSource=BASE)
        selected_tool=sorted(path.relative_to(ROOT).as_posix() for path in (ROOT/TOOL).iterdir() if path.is_file())
        recipe={name:file_identity(ROOT/name,MAX_DOCUMENT) for name in (*RECIPE,*selected_tool)}
        receipt['recipe']=recipe
        receipt['generatedReferenceProject']=identity(REFERENCE_PROJECT.encode())
        phase='normal-nuget-integrity'
        lock=json.loads((ROOT/'sdk/dotnet-guest/probes/smoke/packages.lock.json').read_bytes())
        hashes={name.lower():row['contentHash'] for rows in lock['dependencies'].values() for name,row in rows.items()}
        index_url='https://pkgs.dev.azure.com/dnceng/public/_packaging/dotnet-experimental/nuget/v3/index.json'
        with urllib.request.urlopen(index_url,timeout=30) as incoming:index_raw=incoming.read(262145)
        need(len(index_raw)<=262144,'reference-service-index-limit')
        index=json.loads(index_raw)
        bases=[row['@id'] for row in index['resources'] if row['@type'].startswith('PackageBaseAddress')]
        need(len(bases)==1 and urllib.parse.urlsplit(bases[0]).scheme=='https'
            and urllib.parse.urlsplit(bases[0]).hostname=='pkgs.dev.azure.com'
            and bases[0].endswith('/'),'reference-normal-feed-base')
        base=bases[0]
        packages=(('runtime.wasi-wasm.microsoft.dotnet.ilcompiler.llvm','10.0.0-rc.1.26306.1',base),
                  ('microsoft.net.illink.tasks','10.0.0','https://api.nuget.org/v3-flatcontainer/'))
        package_rows=[]
        for name,version,package_origin in packages:
            target=scratch/(name+'.nupkg');url=package_origin+name+'/'+version+'/'+name+'.'+version+'.nupkg'
            package_rows.append({'name':name,'version':version,'origin':url,'archive':fetch(url,target,commands),
                                 'lockedContentHash':hashes[name]})
        hasher=scratch/'package-hash';hasher.mkdir()
        for name in ('Program.cs','PackageHash.csproj'):
            (hasher/name).write_bytes((ROOT/'sdk/dotnet-guest/tools/package-hash'/name).read_bytes())
        build(commands,'package-hash-build',hasher/'PackageHash.csproj',scratch/'package-hash-bin')
        for row in package_rows:
            actual=commands.run('integrity-'+row['name'],'dotnet',scratch/'package-hash-bin/PackageHash.dll',scratch/(row['name']+'.nupkg')).decode().strip()
            need(actual==row['lockedContentHash'],'reference-normal-nuget-contentHash')
        original=scratch/'System.Private.CoreLib.dll';cecil=scratch/'Mono.Cecil.dll'
        original.write_bytes(selected_member(scratch/(packages[0][0]+'.nupkg'),CORE_MEMBER,8*1024**2,CORE_SHA))
        need(original.stat().st_size==5694976,'reference-original-corelib-size')
        cecil.write_bytes(selected_member(scratch/(packages[1][0]+'.nupkg'),CECIL_MEMBER,512*1024,CECIL_SHA))
        receipt['packages']=package_rows
        immutable={original:file_identity(original,8*1024**2),cecil:file_identity(cecil,512*1024)}
        phase='build-two-source-exact-tools'
        names=commands.run('baseline-source-list','git','ls-tree','-r','--name-only',BASE,'--',TOOL,cwd=ROOT).decode().splitlines()
        need(0<len(names)<=64 and all(name.startswith(TOOL+'/') for name in names),'reference-baseline-source-list')
        materials={}
        for variant in ('baseline','candidate'):
            stage=scratch/variant;stage.mkdir()
            selected=names if variant=='baseline' else selected_tool
            need(len(selected)<=64,'reference-tool-source-limit')
            for number,name in enumerate(selected):
                raw=commands.run('baseline-source-'+str(number),'git','show',BASE+':'+name,cwd=ROOT) if variant=='baseline' else (ROOT/name).read_bytes()
                need(len(raw)<=1024**2,'reference-tool-source-file-limit')
                (stage/Path(name).name).write_bytes(raw)
                materials[variant+':'+name]=identity(raw)
                immutable[stage/Path(name).name]=identity(raw)
            build(commands,variant+'-tool-build',stage/'HttpErrors.csproj',scratch/(variant+'-bin'),cecil)
            for path in (scratch/(variant+'-bin')).iterdir():
                if path.is_file():immutable[path]=file_identity(path,8*1024**2)
        receipt['toolSources']=materials
        phase='old-mode-exact-equality'
        (output/'assemblies').mkdir()
        comparisons=[]
        for mode in ('task-wait','finite-task-wait','managed-task-wait'):
            products=[]
            for variant in ('baseline','candidate'):
                assembly=scratch/(variant+'-'+mode+'.dll');record=scratch/(variant+'-'+mode+'.json')
                commands.run(variant+'-'+mode,'dotnet',scratch/(variant+'-bin/HttpErrors.dll'),'--'+mode,original,assembly,record)
                products.append((bounded(assembly,8*1024**2),bounded(record,MAX_DOCUMENT)))
            need(products[0]==products[1],'reference-old-mode-bytes-or-receipt-changed:'+mode)
            (output/'assemblies'/(mode+'.dll')).write_bytes(products[0][0])
            comparisons.append({'mode':mode,'rawDllAndReceiptEqual':True,'assembly':identity(products[0][0]),'receipt':identity(products[0][1])})
        receipt['oldModeComparisons']=comparisons
        phase='candidate-derivation'
        candidate=scratch/'aggregate.dll';candidate_receipt=scratch/'aggregate.json'
        commands.run('aggregate-derivation','dotnet',scratch/'candidate-bin/HttpErrors.dll','--aggregate-task-wait',original,candidate,candidate_receipt)
        selected=json.loads(bounded(candidate_receipt,MAX_DOCUMENT))
        candidate_bytes=bounded(candidate,8*1024**2)
        candidate_shape(selected,candidate_bytes)
        (output/'assemblies/aggregate.dll').write_bytes(candidate_bytes)
        write_json(output/'candidate.json',selected)
        receipt['candidate']=identity(candidate_bytes)
        immutable[candidate]=identity(candidate_bytes)
        phase='build-host-reference'
        reference=scratch/'reference';reference.mkdir()
        for name in ('ActualCil.cs','Ports.cs','Program.cs'):
            (reference/name).write_bytes(bounded(ROOT/FIXTURE/name,MAX_DOCUMENT))
            immutable[reference/name]=file_identity(reference/name,MAX_DOCUMENT)
        (reference/'Reference.csproj').write_bytes(REFERENCE_PROJECT.encode())
        immutable[reference/'Reference.csproj']=identity(REFERENCE_PROJECT.encode())
        build(commands,'reference-build',reference/'Reference.csproj',scratch/'reference-bin',cecil)
        for path in (scratch/'reference-bin').iterdir():
            if path.is_file():immutable[path]=file_identity(path,8*1024**2)
        phase='generated-il-reference-cases'
        observed_map=None
        runtime=None
        for name in CASES:
            raw=commands.run('case-'+name,'dotnet',scratch/'reference-bin/Reference.dll',candidate,name)
            need(len(raw)<=MAX_DOCUMENT,'reference-case-result-limit')
            value=json.loads(raw)
            mapping=case_shape(value,name,selected)
            actual_runtime={key:value[key] for key in ('runtime','runtimeVersion','hostCoreLibSha256')}
            if observed_map is None:
                observed_map=mapping;runtime=actual_runtime
                write_json(output/'IL-MAP.json',mapping)
            need(mapping==observed_map and actual_runtime==runtime,'reference-case-input-drift')
            del value['cil']
            value['cilIdentity']=file_identity(output/'IL-MAP.json',MAX_DOCUMENT)
            value['rawResult']=identity(raw)
            receipt['cases'].append(value)
        receipt['runtime']=runtime
        need(len(receipt['cases'])==23,'reference-exact-cases')
        phase='final-input-rechecks'
        need(commands.run('final-clean-source','git','status','--porcelain',cwd=ROOT)==b'','reference-source-mutated')
        need({name:file_identity(ROOT/name,MAX_DOCUMENT) for name in recipe}==recipe,'reference-source-material-mutated')
        need(all(file_identity(path,8*1024**2)==expected for path,expected in immutable.items()),'reference-stage-or-product-mutated')
        receipt['immutableProducts']={path.relative_to(scratch).as_posix():value for path,value in immutable.items()}
        receipt['publicFiles']=public_inventory(output,[row['name'] for row in commands.records])
        need(receipt['publicFiles']['assemblies/aggregate.dll']==receipt['candidate']
            and all(receipt['publicFiles']['assemblies/'+row['mode']+'.dll']==row['assembly'] for row in comparisons),
            'reference-public-product-binding')
        commands.check()  # AFTER final source/product/public hashes, never beyond the overall cap.
        receipt['status']='passed'
    except BaseException as error:
        receipt['failedPhase']=phase;receipt['failureType']=type(error).__name__
        failure=error
        raise
    finally:
        receipt['seconds']=time.monotonic()-commands.started
        receipt['privateScratchPurge']='permitted-no-unconfirmed-process-cleanup' if commands.cleanup_safe else 'retained-unconfirmed-process-cleanup'
        try:
            write_json(output/'WAITALL-REFERENCE.json',receipt)
            public_inventory(output,[row['name'] for row in commands.records])
        except BaseException as retention_error:
            # Preserve an original failed phase rather than replacing it with retention.
            if failure is None:raise
            print('reference-retention-failed:'+type(retention_error).__name__,file=sys.stderr)
        finally:
            if commands.cleanup_safe:shutil.rmtree(scratch,ignore_errors=True)
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--admit-evidence',action='store_true')
    args=parser.parse_args()
    if args.admit_evidence:
        result=admit_evidence(args.output)
        print(json.dumps({'evidenceAdmission':result['status'],'originalController':result['originalController']['status']}))
        raise SystemExit(0 if result['status']=='passed' else 1)
    result=qualify(args.output)
    print(json.dumps({'status':result['status'],'cases':len(result['cases']),'nativeAotExecuted':False}))

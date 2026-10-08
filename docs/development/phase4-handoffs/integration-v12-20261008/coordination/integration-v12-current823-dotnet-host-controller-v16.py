from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

COORD=Path(__file__).resolve().parent
OUT=COORD/'integration-v12-current823-dotnet-host-v16'
SOURCE=OUT/'source'
SDK=SOURCE/'sdk/dotnet'
receipt=json.loads((OUT/'source-receipt.json').read_bytes())
assert receipt['head']=='3b7af5096198ae9453b5616bc124def18798911c'
def authenticate():
    for row in receipt['files']:
        data=(SOURCE/row['path']).read_bytes()
        assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
authenticate()
env=dict(os.environ,DOTNET_CLI_TELEMETRY_OPTOUT='1',DOTNET_NOLOGO='1',DOTNET_CLI_USE_MSBUILD_SERVER='0',DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',NUGET_XMLDOC_MODE='skip')
assert subprocess.check_output(['dotnet','--version'],cwd=SDK,env=env,text=True,timeout=20).strip()=='8.0.425'
runtimes=subprocess.check_output(['dotnet','--list-runtimes'],cwd=SDK,env=env,text=True,timeout=20)
assert all(name+' 8.0.31 ' in runtimes for name in ('Microsoft.NETCore.App','Microsoft.AspNetCore.App'))
artifacts=OUT/'build'
properties=['-p:ImportDirectoryBuildProps=false','-p:ImportDirectoryBuildTargets=false','-p:ImportDirectoryPackagesProps=false','-p:UseSharedCompilation=false','-nodeReuse:false']
commands=[]
for project in ('Latent.Sdk.Transport.Tests','Latent.Sdk.SemanticTests'):
    path=project+'/'+project+'.csproj'
    commands.extend([
        ['dotnet','restore',path,'--locked-mode','--configfile','nuget.transport.config','-p:ArtifactsPath='+str(artifacts),'-p:NuGetAuditMode=all',*properties],
        ['dotnet','build',path,'--no-restore','--disable-build-servers','--artifacts-path',str(artifacts),'-v:q',*properties],
        ['dotnet',str(artifacts/'bin'/project/'debug'/(project+'.dll'))],
    ])
start=time.monotonic()
records=[]
assert not (OUT/'host-native-receipt.json').exists()
for index,argv in enumerate(commands,1):
    assert time.monotonic()-start<900
    log=OUT/f'host-step-{index}.log'
    assert not log.exists()
    before=time.monotonic()
    stop=None
    with log.open('xb') as stream:
        process=subprocess.Popen(argv,cwd=SDK,env=env,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
        try:
            process.wait(timeout=min(180,900-(time.monotonic()-start)))
        except subprocess.TimeoutExpired:
            stop='original-180-second-command-deadline'
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=20)
            process.wait(timeout=20)
    data=log.read_bytes()
    assert len(data)<=4*1024**2
    row=dict(argv=argv,returncode=process.returncode,elapsedSeconds=time.monotonic()-before,stopReason=stop,
             originalProcessReaped=process.poll() is not None,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),log=log.name)
    records.append(row)
    print(json.dumps(dict(step=index,returncode=row['returncode'],elapsedSeconds=row['elapsedSeconds'],reaped=row['originalProcessReaped'])),flush=True)
    if process.returncode or stop:break
authenticate()
result=dict(at=datetime.now(timezone.utc).isoformat(),head=receipt['head'],environment='Windows x64 host, pinned .NET8.0.425/runtime8.0.31',
            commands=records,passed=len(records)==len(commands) and all(row['returncode']==0 and row['stopReason'] is None for row in records),
            sourceAllHashesUnchanged=True,allProcessesReaped=all(row['originalProcessReaped'] for row in records),elapsedSeconds=time.monotonic()-start,
            authoritativeLinuxQualification=False,completeCI=False)
(OUT/'host-native-receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='commands'},indent=2),flush=True)

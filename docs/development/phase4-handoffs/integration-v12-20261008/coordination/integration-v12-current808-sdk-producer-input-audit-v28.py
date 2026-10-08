from pathlib import Path
import hashlib
import json
import subprocess

repo = Path(r'C:\Users\turkins\Desktop\latent-fabric')
coord = Path(__file__).resolve().parent
heads = {'808':'1e129ef0ed6682c998f81a498e76bd4de61c6fec',
         '811':'335dca010d299e554a4ab351e9fb525ae15e8d5c'}
paths = [
    'sdk/profile/client-profile.json',
    'tools/generate_node_rpc.py',
    'sdk/dotnet/Latent.Sdk/Latent.Sdk.csproj',
    'sdk/dotnet/Latent.Sdk.Transport/Latent.Sdk.Transport.csproj',
    'sdk/dotnet/Latent.Sdk.Transport/packages.lock.json',
    'sdk/dotnet/Latent.Sdk.Transport.Tests/packages.lock.json',
    'sdk/dotnet/validate.py',
    'sdk/dotnet/global.json',
    'sdk/dotnet/protobuf.lock.json',
    'sdk/typescript-client/src/node/protocol/generated.ts',
]
rows=[]
for path in paths:
    values={}
    for name,head in heads.items():
        result=subprocess.run(['git','show',head+':'+path],cwd=repo,capture_output=True)
        values[name]=hashlib.sha256(result.stdout).hexdigest() if result.returncode==0 else None
    rows.append(dict(path=path, hashes=values, bytesIdentical=values['808']==values['811'],
        existsInBoth=all(values.values())))
result=dict(heads=heads, rows=rows, actualCodeGenerationOrBuildClaimed=False)
out=coord/'integration-v12-union-review/current808-sdk-producer-input-audit-v28.json'
out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))

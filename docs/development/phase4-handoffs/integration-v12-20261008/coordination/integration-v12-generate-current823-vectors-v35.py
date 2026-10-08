from pathlib import Path
import os
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr823-witness-vector-v35')
paths=['api/proto','sdk/rust/src','sdk/rust/tests',
       'sdk/java-client/src/main','sdk/java-client/src/test',
       'sdk/dotnet/Latent.Sdk','sdk/dotnet/Latent.Sdk.SemanticTests',
       'sdk/c/include','sdk/c/tests']
subprocess.run(['git','sparse-checkout','add',*paths],cwd=root,check=True)
env=dict(os.environ)
formatter=Path(r'C:\Users\turkins\Desktop\latent-phase4-coordination\root-private-go127-windows-formatter-20261007-v1\go\bin')
assert (formatter/'gofmt.exe').is_file()
env['PATH']=str(formatter)+os.pathsep+env['PATH']
env['RUSTUP_TOOLCHAIN']='1.97.1'
subprocess.run(['python','-X','utf8','-B','sdk/profile/generate.py','--write'],cwd=root,env=env,check=True,timeout=120)
subprocess.run(['python','-X','utf8','-B','sdk/profile/generate.py','--check'],cwd=root,env=env,check=True,timeout=120)
subprocess.run(['python','-X','utf8','-B','sdk/profile/test_profile.py'],cwd=root,env=env,check=True,timeout=120)

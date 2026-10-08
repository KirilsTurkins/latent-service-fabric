from pathlib import Path
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-pr828-current-java-union-v12')
parent='45067c6d52269a61d00c2f077992a4105736128e'
def git(*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
assert git('rev-parse','HEAD')==parent and not git('status','--porcelain')
name='apps/latentd/src/command/inspect_transactions.rs'
raw=subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{name}']).decode()
old='''    let mut bytes = serde_json::to_vec(&report)
        .map_err(|_| Failure::new("status", PlatformErrorCode::Internal))?;
    if bytes.len() >= 256 * 1024 {
        return Err(Failure::new("status", PlatformErrorCode::ResourceExhausted));
    }
    bytes.push(b'\\n');
    std::io::stdout()
        .lock()
        .write_all(&bytes)
        .map_err(|_| Failure::new("status", PlatformErrorCode::Unavailable))'''
assert raw.count(old)==1
raw=raw.replace('use std::{io::Write, path::Path};','use std::path::Path;')
raw=raw.replace(old,'    super::status::inspection(&report)')
path=root/name
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(raw,encoding='utf8',newline='\n')
print(json.dumps({'parent':parent,'changedPath':name,'maximumJsonBytes':262144,
 'ownerRuntimeAndRetirementUnchanged':True,'serializerAlreadyQualifiedAt':'291f6f13da92aa675b5caa955b26e2c27f395d05'}))

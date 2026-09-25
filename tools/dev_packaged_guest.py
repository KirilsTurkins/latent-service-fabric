"""Read public build artifacts and isolation observations from an exact owned user."""
import base64
import json
import os
from pathlib import Path
import re

if __package__:
    from .dev_packaged_process import Command, digest, read_json, require
else:
    from dev_packaged_process import Command, digest, read_json, require

# This observer never loads application recipes or credential contents. It runs
# as the selected workspace user, and exports only the three public build files.
OBSERVER = r'''
import base64,hashlib,json,os,pwd,re,stat,sys
from pathlib import Path
name,mode,*options=sys.argv[1:]
assert re.fullmatch(r'test-packaged-(rust|c|java|dotnet|go|typescript)',name)
account=pwd.getpwuid(os.getuid()); assert os.getuid()!=0
root=Path(account.pw_dir)/'.lsf-dev'/name
def document(path):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size<=262144
    return json.loads(path.read_bytes())
assert document(root/'owner.json')['id']==name
if mode=='audit':
    credential=root/'runtime/config/client/client.json'
    info=credential.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and info.st_mode&0o077==0
    snapshots=list((root/'snapshots').iterdir());assert len(snapshots)<=4
    names=[entry['path'] for item in snapshots for entry in document(item/'snapshot.json')['files']]
    assert not any('.env' in Path(item).parts or '.ssh' in Path(item).parts for item in names)
    assert all(not (item/'app/.env').exists() for item in snapshots)
    result={'uid':os.getuid(),'gid':os.getgid(),'user':account.pw_name,'kernel':os.uname().release,
        'architecture':os.uname().machine,'osRelease':Path('/etc/os-release').read_text()[:8192],
        'privateCredentialMode':stat.S_IMODE(info.st_mode),'credentialContentsRead':False,
        'sourceCredentialExcluded':True,'snapshotFiles':len(names)}
    if options:
        other=options[0];assert re.fullmatch(r'lsfd-[a-f0-9]{12}',other) and other!=account.pw_name
        try:list((Path('/home')/other).iterdir())
        except PermissionError:result['otherWorkspaceHomeDenied']=True
        else:raise AssertionError('other workspace home readable')
elif mode=='artifact':
    key,attempt,offset=options;assert key in {'component','capsule','contracts'} and re.fullmatch(r'[a-f0-9]{32}',attempt)
    receipt=document(root/'last-build.json')['receipt'];assert receipt['attempt']==attempt
    descriptor=document(root/'project.json')['descriptor'];relative=descriptor['artifacts'][key]
    assert relative and not relative.startswith('/') and all(p not in {'','.','..'} for p in relative.split('/'))
    parent=root/'builds'/attempt/'source';path=parent
    for part in relative.split('/'):
        path=path/part;assert not path.is_symlink()
    info=path.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=16777216
    with path.open('rb') as stream:checksum='sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()
    assert checksum==receipt['artifacts'][key]
    offset=int(offset);assert 0<=offset<info.st_size
    with path.open('rb') as stream:stream.seek(offset);raw=stream.read(1048576)
    result={'key':key,'size':info.st_size,'sha256':checksum,'offset':offset,'bytes':base64.b64encode(raw).decode()}
else:raise AssertionError('closed observer operation')
print(json.dumps(result,sort_keys=True))
'''


def observe(api, item, mode, *arguments):
    config = read_json(api.state / item['workspace'] / 'backend.json')
    require(config['kind'] == 'wsl2' and config['user'] == item['user']
            and re.fullmatch(r'LSF-Dev-[a-f0-9]{16}', config['distribution'])
            and re.fullmatch(r'lsfd-[a-f0-9]{12}', item['user']), 'owned-wsl-observer-target')
    require(len(api.report['commands']) < 190, 'qualification-command-count-limit')
    command = Command([Path(os.environ['SystemRoot']) / 'System32/wsl.exe', '--distribution', config['distribution'],
        '--user', item['user'], '--exec', '/usr/local/bin/python3.13', '-I', '-B', '-c', OBSERVER,
        item['workspace'], mode, *arguments], api.root, api.env)
    try:
        require(command.finish(30) == 0, 'owned-wsl-public-observation-failed')
        return json.loads(command.raw())
    finally:
        try:
            command.abort_controller()
        finally:
            api.report['commands'].append({**command.receipt(), 'purpose': 'read-only-owned-guest-observation'})


def export(api, item, *, suffix=''):
    project = Path(item['project'])
    descriptor = read_json(project / 'latent.project.json')
    require(suffix in {'', '-revision-b'}, 'closed-public-artifact-export-slot')
    root = api.root / (item['workspace'] + '-public-artifacts' + suffix)
    root.mkdir(mode=0o700)
    retained = {}
    for key in ('component', 'capsule', 'contracts'):
        relative = descriptor['artifacts'][key]
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts, 'public-artifact-path')
        target = root / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        offset = 0
        with target.open('xb') as stream:
            while True:
                result = observe(api, item, 'artifact', key, item['build']['attempt'], str(offset))
                require(result['key'] == key and result['offset'] == offset and 0 < result['size'] <= 16777216
                        and result['sha256'] == item['build']['artifacts'][key], 'public-artifact-observation-identity')
                chunk = base64.b64decode(result['bytes'], validate=True)
                require(0 < len(chunk) <= 1048576 and offset + len(chunk) <= result['size'], 'public-artifact-chunk-limit')
                stream.write(chunk)
                offset += len(chunk)
                if offset == result['size']:
                    break
        require(digest(target) == result['sha256'], 'public-artifact-export-digest')
        retained[key] = {'sha256': result['sha256'], 'size': offset}
    return {'directory': str(root), 'files': retained, 'source': 'exact-owned-build-read-only-export'}

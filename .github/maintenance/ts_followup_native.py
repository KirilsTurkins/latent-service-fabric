#!/usr/bin/env python3
"""Verify the selected ioctl boundary, then repair its stale exact pin guard."""
import hashlib,io,json,os,pathlib,subprocess,sys,tarfile,urllib.request
root=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-parent'
out=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-evidence';out.mkdir(exist_ok=True)
def digest(raw):return hashlib.sha256(raw).hexdigest()
archives={}
for version,expected in [('1.1.5','891efababe418670775f199f0d233d84843c227a0949a883ce15b37c78d6629d'),('1.1.6','e5e76742e5294153d4dde1207dbec5bdd81eef6fabdc0d2118babadabfd858aa')]:
    with urllib.request.urlopen('https://static.crates.io/crates/rustix/rustix-'+version+'.crate',timeout=90) as response:raw=response.read(8*1024*1024+1)
    assert len(raw)<=8*1024*1024 and digest(raw)==expected,('rustix-archive-identity',version)
    files={};prefix='rustix-'+version+'/'
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):continue
            name=member.name[len(prefix):]
            if name.startswith(('src/ioctl/','src/backend/linux_raw/io/','src/backend/libc/io/')) or name in ('src/backend/linux_raw/conv.rs','src/backend/linux_raw/reg.rs','src/backend/linux_raw/arch/x86_64.rs'):
                assert name not in files;files[name]=tar.extractfile(member).read()
    assert 'src/ioctl/mod.rs' in files and 'src/backend/linux_raw/io/syscalls.rs' in files
    archives[version]={'sha256':expected,'bytes':len(raw),'files':files}
a,b=(archives[v]['files'] for v in ('1.1.5','1.1.6'))
assert set(a)==set(b) and all(a[p]==b[p] for p in a),'ioctl-boundary-change-requires-review'
factory=root/'crates/latent-stream-factory-native/src/lib.rs'
assert digest(factory.read_bytes())=='47233b07b205adfd04cfbd22b47632576cf564d56effd6e21e675defec1b88f7'
p=root/'tools/native_loader_boundary.py';raw=p.read_bytes();assert digest(raw)=='c1a192f5c6c8d5460a84c81d3a6579d08c4d64c6beb9a2a1fc4b36c6039f1bfe'
s=raw.decode();assert s.count('"=1.1.5"')==1;p.write_text(s.replace('"=1.1.5"','"=1.1.6"'))
p=root/'tools/tests/test_native_loader_boundary.py';raw=p.read_bytes();assert digest(raw)=='97f382b40940b0f0a97b7c3f1c080fde97d0b844514e8575b863fcec0ab3efcc'
s=raw.decode();before='rustix = { version = "=1.1.5", features = ["fs"] }';assert s.count(before)==1;s=s.replace(before,before.replace('1.1.5','1.1.6'))
before="manifest.replace('=1.1.5', '=1.1.6'),";assert s.count(before)==1;s=s.replace(before,"manifest.replace('=1.1.6', '=1.1.5'),\n                        manifest.replace('=1.1.6', '=1.1.7'),")
needle='    def test_actual_guest_matches_the_two_closed_profile_generators(self) -> None:\n'
addition='''    def test_actual_stream_factory_matches_the_reviewed_target(self) -> None:
        import tomllib
        actual = Path(__file__).resolve().parents[2]
        workspace = tomllib.loads((actual / "Cargo.toml").read_text())['workspace']
        self.assertEqual(boundary.validate_stream_factory(actual, workspace['lints']['clippy']), [])

'''
assert s.count(needle)==1;p.write_text(s.replace(needle,addition+needle))
for label,args in [('native-boundary-source',[sys.executable,'-B','-m','unittest','tools.tests.test_native_loader_boundary','-v']),('native-fd-owner',['cargo','test','-p','latent-stream-factory-native','--locked'])]:
    with (out/(label+'.log')).open('wb') as f:result=subprocess.run(args,cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=600)
    print(label,'exit',result.returncode,flush=True)
    if result.returncode:print((out/(label+'.log')).read_text()[-12000:])
    assert result.returncode==0,label
record={'schema':1,'workflowRun':int(os.environ['GITHUB_RUN_ID']),'factorySourceSha256':digest(factory.read_bytes()),'archives':{v:{k:d[k] for k in ('sha256','bytes')} for v,d in archives.items()},'unchangedBoundaryFiles':{p:{'sha256':digest(b[p]),'bytes':len(b[p])} for p in sorted(b)},'scope':'Exact 1.1.6 target selection retains the unchanged protected ioctl and std OwnedFd adoption/drop boundary. Source mutation, dependency downgrade/unreviewed upgrade, target/build/lint changes remain refused. Native regular-file refusal and real FD adoption/drop executed; no custom-kernel factory mint, decommit or cross-tenant qualification claimed.'}
p=root/'docs/evidence/ci-rustix-factory-boundary-2026-11-14.json';p.write_text(json.dumps(record,indent=2)+'\n');(out/'rustix-boundary-review.json').write_bytes(p.read_bytes())
subprocess.run(['git','add','tools/native_loader_boundary.py','tools/tests/test_native_loader_boundary.py',str(p)],cwd=root,check=True)
subprocess.run(['git','diff','--cached','--check'],cwd=root,check=True)
subprocess.run(['git','commit','-m','fix(ci): bind the reviewed rustix ioctl boundary to selected 1.1.6'],cwd=root,check=True)

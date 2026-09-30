from pathlib import Path
import subprocess, json, re, hashlib
root=Path.cwd()
HEAD='260c01eb4039f6c48fa4912ffcaf53184e404769'
BASE='b40a31aa7e63128698df2be86324657b4d22a590'
subprocess.run(['git','checkout','--detach',HEAD],check=True)
subprocess.run(['git','update-ref','refs/remotes/origin/input-base',BASE],check=True)
result=subprocess.run(['git','merge','--no-commit','--no-ff',BASE])
assert result.returncode == 1
conflicts=subprocess.check_output(['git','diff','--name-only','--diff-filter=U']).decode().splitlines()
assert len(conflicts)==19,conflicts
def source(ref,path): return subprocess.check_output(['git','show',f'{ref}:{path}'],cwd=root).decode()
def put(path,text): (root/path).write_text(text)
def take(ref,path): put(path,source(ref,path))
def resolve_hunks(path, choices):
 text=(root/path).read_text(); matches=list(re.finditer(r'^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n',text,re.M|re.S))
 assert len(matches)==len(choices),(path,len(matches),choices)
 it=iter(choices)
 text=re.sub(r'^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n',lambda m:m.group(next(it)),text,flags=re.M|re.S)
 put(path,text)
# Equivalent source behavior or a strict superset of test expectations from development.
for path in [
 'crates/latent-wasmtime/src/values/signature.rs',
 'packaging/linux/license-sources.json',
 'tools/dev_workflow/build_cache.py',
 'tools/ci/contracts/owners/tools/ci_fast.py.json',
 'tools/ci/contracts/owners/tools/phase3_security.py.json',
 'tools/ci/contracts/owners/tools/run_security_profile_workflow.py.json',
 'tools/ci/contracts/python/test_dev_node_policies.py.json',
 'tools/ci/contracts/python/test_native_loader_boundary.py.json',
 'tools/ci/contracts/python/test_native_runtime.py.json',
 'tools/ci/contracts/python/test_node_security_profile_schema.py.json',
 'tools/ci/contracts/workflows/ci.yml/jobs/msrv.json',
]: take('origin/input-base',path)
# Take the union of independently reviewed case sets; all common guards agree.
path='tools/ci/contracts/python/test_dev_build_cache.py.json'
a=json.loads(source('HEAD',path)); b=json.loads(source('origin/input-base',path))
assert all(a['guards'][k]==b['guards'][k] for k in a['guards'].keys()&b['guards'].keys())
a['cases']=sorted(set(a['cases'])|set(b['cases'])); a['guards'].update(b['guards'])
a['reviewReason']='PR #703 merge: retain every reviewed build-attempt and managed-SDK boundary regression from both branches; existing test execution and skip guards are unchanged.'
put(path,json.dumps(a,indent=2,sort_keys=True)+'\n')
# Keep the newer authenticated package selections, not the older development bundle.
for path in ['website/toolchain/source.json','website/toolchain/package-lock.json','.github/security/inventory.json']:
 take('HEAD',path)
# Both sets of scanner regression assertions, without duplicates or downgrades.
path='tools/tests/test_security_baseline.py'
resolve_hunks(path,[1]); text=(root/path).read_text(); text=text.replace('        self.assertIn(("brace-expansion", "5.0.12"), values)\n','        self.assertIn(("brace-expansion", "5.0.12"), values)\n        self.assertIn(("balanced-match", "4.0.4"), values)\n')
put(path,text)
# Preserve pre-execution graph and shadowing rejection, adding development's old-graph guard.
path='website/toolchain/prepare.py'
text=source('HEAD',path)
old='if (dependency.get("name") != "balanced-match" or dependency.get("version") != "4.0.4"'
assert old in text
text=text.replace(old,'if (old.get("dependencies") != expected\n                    or dependency.get("name") != "balanced-match" or dependency.get("version") != "4.0.4"')
put(path,text)
# Retain all automatically combined test methods, then resolve only overlapping hunks.
path='website/toolchain/tests/test_prepare.py'
resolve_hunks(path,[1,2,1]); text=(root/path).read_text()
old="('package/node_modules/brace-expansion/package.json', {'name': 'brace-expansion', 'version': '5.0.9'}),"
assert old in text
text=text.replace(old,"('package/node_modules/brace-expansion/package.json', {'name': 'brace-expansion', 'version': '5.0.9',\n                         'dependencies': {'balanced-match': '^4.0.2'}}),")
# Exercise the additional old-graph guard, while preserving the existing replacement tests.
needle="        for version in ('4.0.1', '5.0.0'):\n"
assert needle in text
text=text.replace(needle,"        for graph in ({}, {'balanced-match': '^5.0.0'}, {'unexpected': '1.0.0'}):\n            changed = [(path, {**value, 'dependencies': graph}\n                        if path == 'package/node_modules/brace-expansion/package.json' else value)\n                       for path, value in self.base]\n            with self.subTest(original_graph=graph), self.assertRaisesRegex(ValueError, 'graph requires review'):\n                prepare.compose(archive(changed), self.patches)\n"+needle)
put(path,text)
# Combine bounded and stable-file hashing with the development checkpoint's exact-bound tests.
path='crates/latent-wasmtime/tests/phase3_resource/observation.rs'
text=source('HEAD',path)
old='pub fn file_digest(path: &Path) -> String {\n    let mut file = fs::File::open(path).unwrap();'
new='pub fn file_digest(path: &Path) -> String {\n    file_digest_with_limit(path, MAX_EXECUTABLE_BYTES)\n}\n\nfn file_digest_with_limit(path: &Path, maximum: u64) -> String {\n    let mut file = fs::File::open(path).unwrap();'
assert old in text
text=text.replace(old,new).replace('assert!(metadata.len() <= MAX_EXECUTABLE_BYTES);','assert!(metadata.len() <= maximum);')
dev=source('origin/input-base',path)
start=dev.index('// Run within the existing registered checkpoint')
end=dev.index('pub fn publish(',start)
checks=dev[start:end].replace('digest_reader(Cursor::new(payload), 8)','read_digest(Cursor::new(payload), 8).0').replace('digest_reader(Cursor::new([]), 0)','read_digest(Cursor::new([]), 0).0').replace('digest_reader(Cursor::new(payload), 7)','read_digest(Cursor::new(payload), 7)')
text=text.replace('pub fn publish(',checks+'pub fn publish(',1)
put(path,text)
# These are historical qualification records, not current runtime pins.
for version in [2,3]: take('HEAD',f'wit/host-abi-phase3-v{version}.json')
# De-duplicate the automatically merged current/historical documentation headings.
path='docs/development/wasmtime-security-update.md'
text=(root/path).read_text()
text=text.replace('\n\n## Historical September 13 baseline\n\n### Wasmtime 47.0.4 security baseline\n\n## September 29, 2026: Wasmtime 48.0.3 security baseline\n','\n\n### Runtime containment and regression coverage\n')
text=text.replace('## Earlier security update\n','## Historical September 13 baseline\n\n### Wasmtime 47.0.4 security baseline\n')
put(path,text)
# Bind the merged builder and isolated manifest to their exact reviewed bytes.
path='.github/security/inventory.json'
text=(root/path).read_text(); data=json.loads(text)
old=json.loads(source('HEAD',path))
def digest(path): return hashlib.sha256((root/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
# Keep the file's compact formatting; replace only the two scoped fingerprints.
for old_hash, new_hash in [
 ('7cfd7f82a9ae4e1e464f5c30b4b4fd879a97577c59d5bc3cdd6a2fbc25345f06',digest('website/toolchain/prepare.py')),
 ('bbde879116b5088faaed9bab6b4b8541d8891812ac9e0c097b3e1a2bf6376069',digest('tools/native-fixture/Cargo.toml')),
]:
 assert old_hash in text
 text=text.replace(old_hash,new_hash)
put(path,text)
# Preserve development's Cargo-generated graph, changing only the original serde_json selection.
path='Cargo.lock'
dev=source('origin/input-base',path); ours=source('HEAD',path)
pattern=r'\[\[package\]\]\nname = "serde_json"\n.*?(?=\n\[\[package\]\]|\Z)'
m=re.search(pattern,ours,re.S); assert m and '1.0.151' in m[0]
assert len(re.findall(pattern,dev,re.S))==1
put(path,re.sub(pattern,lambda _:m[0],dev,flags=re.S))
path='tools/tests/test_native_loader_boundary.py'
text=(root/path).read_text()
old='''        for name in ("v2", "v3", "v4"):
            with self.subTest(descriptor=name):
                descriptor = json.loads((root / f"wit/host-abi-phase3-{name}.json").read_text())
                self.assertEqual(descriptor["wasmtimeVersion"], "48.0.3")'''
new='''        # Only v4 is active. Superseded matrices retain their tested runtime,
        # independently fingerprinted by test_host_abi_profile.
        for name, version in (("v2", "47.0.4"), ("v3", "47.0.4"), ("v4", "48.0.3")):
            with self.subTest(descriptor=name):
                descriptor = json.loads((root / f"wit/host-abi-phase3-{name}.json").read_text())
                self.assertEqual(descriptor["wasmtimeVersion"], version)'''
assert old in text; put(path,text.replace(old,new))
subprocess.run(['git','add','--all'],check=True)
subprocess.run(['git','diff','--cached','--check'],check=True)
assert not subprocess.check_output(['git','ls-files','-u'])
tree=subprocess.check_output(['git','write-tree']).decode().strip()
assert tree=='0c7f8ad6d5f0337364bae6f9f268029801ab5041',tree
print('Verified exact locally reviewed merge tree:',tree)

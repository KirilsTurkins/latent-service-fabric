import hashlib, json, os, pathlib, subprocess
H = 'f881e760dfb527e341b2b43b60d99f217ad2d8ae'
D = '702bd725f259a241a9b92aecde9b1a5787b94f94'
B = '57d4a349dbb70c2511be1cd15f41e5915d6ba5b9'
root = pathlib.Path('source').resolve()
out = pathlib.Path(os.environ['RUNNER_TEMP']) / 'pr2151'
out.mkdir(exist_ok=True)
def git(*args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
def text(*args):
    return git(*args).stdout.decode().strip()
def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
assert text('rev-parse', 'HEAD') == H
assert text('merge-base', H, D) == B
patch = pathlib.Path('input/.github/pr2151-resolution.patch').read_bytes()
assert hashlib.sha256(patch).hexdigest() == 'bd3881adfdda6b045c700743d44718a156f848b852add69de95b92e6e2246b25'
rows = '''H sdk/java-guest/README.md 5e61426b330274724fe2b9ddb93fbe380cd71227 9fb2375f680e8f44120be28530b24a4a4537f609
H sdk/typescript-guest/README.md 68d59950a0e09541556e862309fef5dee188c080 8328d7aea0e8b04ea25aa59d345a2563c2e37ad3
H sdk/typescript-guest/activation/native_engine.cpp 07d02a6142c7c9d610717af7c5479c2724c11857 07d02a6142c7c9d610717af7c5479c2724c11857
D sdk/typescript-guest/activation/native_objects.h ea0fd0215b2edfd6ae1a5050f2c253b7e3ca6f49 ea0fd0215b2edfd6ae1a5050f2c253b7e3ca6f49
H tools/java_guest/date_link_guard.py 74354dd0655050b29ad819d54e1ec65bea28cd05 d31c359c1e7599846fd769564c8414e892e61cd1
D tools/java_guest/enum_guard.py 8ce4ad27744c082481ed4389ac62ecbcc233c377 7a4f9edbd67135157a45a2eb3efbdd60a780cbf2
D tools/tests/fixtures/typescript_abort_lazy_algorithms.cpp e1938901b71f57a5bc31df4e6c7a04507eb933c0 a95c7e412cbdfe8f8afce6e89f25392145114525
H tools/tests/fixtures/typescript_graph_pressure.cpp e51b18e2b7e9d2ba1a04e706a22896411ef3794c 69c8c747fb01335990c816ca559908d7b0259d8e
D tools/tests/test_java_date_link_guard.py a3786c1d8729f20b1579b4b869143ccbd75b0d7d a3786c1d8729f20b1579b4b869143ccbd75b0d7d
D tools/tests/test_java_enum_guard.py ce6fde5d99a75be4b936bc068c689f8f7a210ba2 fa52cdbb7a54a6328def501d68c43697ca0b3f15
D tools/tests/test_java_exception_slots.py 34279dbc5fc2cbff2b9b498dd3298b2949bac09c cae27ebe75e07b172a8f424ea431591bdf031063
D tools/tests/test_java_linear_stack.py 94fef0a9348bdc816439c9ac7756242942171054 21135d2db0bca576bdd42ed99c937b8c444bc9fe
D tools/tests/test_local_tests.py 4536df80e1dbf08d36b47e011f87b05c969ee11f 033dd84285294fb7a8d3af920b69d3157be24123
H tools/tests/test_typescript_event_ownership.py 8d13702f7cbcd263bb0060a4c47d88c277af09da 24524a9896499f7e166a4192f0c38243e4a7b67f
D tools/typescript_guest/event_engine.py 988edcd201aaa7f9306d3984e7284035a6b957c4 b474676e6d8f14c1632222bd0953684a47fc3531'''.splitlines()
plan = [line.split() for line in rows]
paths = {row[1] for row in plan}
assert len(paths) == 15
merge = git('-c', 'user.name=LSF resolution preparation', '-c', 'user.email=resolution@invalid.example',
            'merge', '--no-commit', '--no-ff', D, check=False)
print(merge.stdout.decode(), merge.stderr.decode())
assert merge.returncode in (0, 1)
assert text('rev-parse', 'MERGE_HEAD') == D
conflicts = set(text('diff', '--name-only', '--diff-filter=U').splitlines())
assert conflicts <= paths, sorted(conflicts - paths)
for label, path, before, after in plan:
    raw = git('show', {'H':H, 'D':D}[label] + ':' + path).stdout
    assert blob(raw) == before, path
    target = root / path
    assert not target.is_symlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
git('apply', '--check', str(pathlib.Path('input/.github/pr2151-resolution.patch').resolve()))
git('apply', str(pathlib.Path('input/.github/pr2151-resolution.patch').resolve()))
for label, path, before, after in plan:
    assert blob((root/path).read_bytes()) == after, path
git('add', '--', *sorted(paths))
assert not text('diff', '--name-only', '--diff-filter=U')
ours = set(text('diff', '--name-only', B, H).splitlines())
theirs = set(text('diff', '--name-only', B, D).splitlines())
def identity(ref, path):
    return git('ls-tree', ref, '--', path).stdout
# Check all non-overlapping changes, not just a selected preservation list.
T = text('write-tree')
for ref, changed in [(H, ours-theirs-paths), (D, theirs-ours-paths)]:
    for path in changed:
        assert identity(T,path) == identity(ref,path), path
for path in ours & theirs - paths:
    if identity(H,path) == identity(D,path):
        assert identity(T,path) == identity(D,path), path
for path in ('Cargo.lock','crates/latent-wasmtime/src/native_stacks.rs','tools/typescript_guest/source_splicer.mjs',
             'tools/typescript_guest/abort_engine.py','tools/java_guest/exception_slots.py',
             'sdk/typescript-guest/probes/fetch-runtime/main.ts','sdk/dotnet-guest/tools/http-errors/AggregateTaskWait.cs'):
    assert identity(T,path) == identity(D,path), path
for path in ('sdk/java-guest/fibers/dev/latent/guest/runtime/concurrent/ManagedExecutor.java',
             'sdk/java-guest/fibers/conformance/shutdown-now/Capsule.java',
             'tools/java_guest/field_read_patch.py','tools/java_guest/coroutine_patch.py',
             'tools/java_standard_http_library.py','tools/qualify_java_dependency_suite.py'):
    assert identity(T,path) == identity(H,path), path
assert not any('pr2151-resolution' in path for path in text('ls-tree','-r','--name-only',T).splitlines())
git('diff', '--cached', '--check')
(out/'tree.txt').write_text(T+'\n')
(out/'merge-conflicts.json').write_text(json.dumps(sorted(conflicts),indent=2)+'\n')
print('PREPARED_TREE',T)

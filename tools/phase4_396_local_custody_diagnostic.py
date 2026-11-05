"""Branch-only source and test-inventory controls for the #396 custody split."""
import ast
from collections.abc import Iterator
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / 'custody-diagnostic'
BASE = '7a256b9ed60362888706aca72361d02b9ba729db'


def check_graph():
    parent = subprocess.check_output(['git', 'rev-parse', 'HEAD^'], text=True).strip()
    assert parent == BASE, parent
    subprocess.run(['git', 'diff', '--exit-code', BASE, 'HEAD', '--',
                    'tools/validate_foundation.py', 'crates/latent-http/',
                    'crates/latent-blobs/src/local/fs.rs',
                    'crates/latent-blobs/src/s3.rs', 'crates/latent-blobs/src/s3/'], check=True)
    old_root = 'crates/latent-blobs/src/'
    new_root = 'crates/latent-local-blobs/src/'
    originals = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, '--',
                 old_root + 'local.rs', old_root + 'local/', old_root + 'provider.rs',
                 old_root + 'provider/'], text=True).splitlines()
    assert len(originals) == 17 and len(set(originals)) == 17
    for original in originals:
        assert original.startswith(old_root)
        relative = original.removeprefix(old_root)
        moved = ROOT / (new_root + relative)
        data = subprocess.check_output(['git', 'show', BASE + ':' + original])
        assert moved.read_bytes() == data, original
        retained = ROOT / original
        assert retained.is_file() if relative == 'local/fs.rs' else not retained.exists(), original
    matrix_path = 'tools/phase3_security_cases.py'
    original_matrix = subprocess.check_output(['git', 'show', BASE + ':' + matrix_path])
    old_owner = b'library("blob-storage", "crates/latent-blobs", "latent_blobs", "real-filesystem-provider",'
    new_owner = b'library("blob-storage", "crates/latent-local-blobs", "latent_local_blobs", "real-filesystem-provider",'
    assert original_matrix.count(old_owner) == 1
    assert (ROOT / matrix_path).read_bytes() == original_matrix.replace(old_owner, new_owner, 1)
    source = (ROOT / 'tools/validate_foundation.py').read_text(encoding='utf-8')
    names = {'dependency_specifications', 'workspace_dependency_graph', 'validate_workspace_dependency_graph'}
    selected = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == names
    errors = []
    scope = {'ROOT': ROOT, 'Path': Path, 'Iterator': Iterator, 'tomllib': tomllib, 'fail': errors.append}
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<unchanged-validator>', 'exec'), scope)
    graph = scope['workspace_dependency_graph'](ROOT)
    scope['validate_workspace_dependency_graph'](ROOT)
    assert len(graph) == 56 and not errors, (len(graph), errors)
    for owner, dep in [('latent-commit', 'latent-local-blobs'), ('latent-blobs', 'latent-local-blobs'),
                       ('latent-blobs', 'latent-http'), ('latent-http', 'latent-commit')]:
        assert dep in graph[owner], (owner, dep)
    assert 'latent-blobs' not in graph['latent-commit']
    print('unchanged workspace validator: 56 members, no cycles, required edges preserved')
    print('original HTTP and S3 sources unchanged; all 17 custody files moved byte-for-byte')
    print('original Phase 3 security case matrix changed only its exact custody owner')


def declared(path, prefix):
    text = (ROOT / path).read_text(encoding='utf-8')
    pattern = r'#\[(?:tokio::)?test\]\s*(?:async\s+)?fn\s+(\w+)\s*\('
    return {prefix + name for name in re.findall(pattern, text)}


def listed(path):
    lines = path.read_text(encoding='utf-8').splitlines()
    result = [line.removesuffix(': test') for line in lines if line.endswith(': test')]
    assert len(result) == len(set(result)), 'duplicate discovered test names'
    return set(result)


def check_inventory():
    expected_local = declared('crates/latent-local-blobs/src/local/tests.rs', 'local::tests::')
    for name in ('capacities', 'durable', 'failures', 'security'):
        expected_local |= declared('crates/latent-local-blobs/src/local/tests/' + name + '.rs', 'local::tests::' + name + '::')
    expected_s3 = declared('crates/latent-blobs/src/s3/inventory/tests.rs', 's3::inventory::tests::')
    for name in ('signing', 'xml'):
        expected_s3 |= declared('crates/latent-blobs/src/s3/' + name + '.rs', 's3::' + name + '::tests::')
    assert len(expected_local) == 29 and len(expected_s3) == 7
    actual_local = listed(REPORTS / 'local-list.txt')
    actual_facade = listed(REPORTS / 'blobs-list.txt')
    actual_commit = listed(REPORTS / 'commit-list.txt')
    original_commit = listed(REPORTS / 'original-commit-list.txt')
    new_control = 'local_facade_type_tests::local_facade_reexports_the_original_custody_types'
    assert actual_local == expected_local, ('local inventory mismatch', sorted(expected_local - actual_local), sorted(actual_local - expected_local))
    assert actual_facade == expected_s3 | {new_control}, ('S3 inventory mismatch', sorted(expected_s3 - actual_facade), sorted(actual_facade - expected_s3 - {new_control}))
    assert actual_commit and actual_commit == original_commit, ('commit inventory mismatch',
        sorted(original_commit - actual_commit), sorted(actual_commit - original_commit))
    sys.path.insert(0, str(ROOT))
    from tools.phase3_security_cases import GROUPS
    from tools.phase3_security_artifacts import validate_selection
    group, = [g for g in GROUPS if g.key == 'blob-storage']
    assert group.manifest == 'crates/latent-local-blobs/Cargo.toml' and group.target == 'latent_local_blobs'
    assert len(group.cases) == 8
    validate_selection(group, frozenset(actual_local), frozenset())
    print('all eight original security-matrix cases select the discovered custody executable')
    print(f'actual discovery: 29 original local, seven original S3, one facade type-identity, {len(actual_commit)} exactly retained commit tests')


if __name__ == '__main__':
    if sys.argv[1:] == ['graph']:
        check_graph()
    elif sys.argv[1:] == ['inventory']:
        check_inventory()
    else:
        raise SystemExit('expected graph or inventory')

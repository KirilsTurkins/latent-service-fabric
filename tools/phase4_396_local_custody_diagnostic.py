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
                    'crates/latent-blobs/src/local.rs', 'crates/latent-blobs/src/local/',
                    'crates/latent-blobs/src/provider.rs', 'crates/latent-blobs/src/provider/',
                    'crates/latent-blobs/src/s3.rs', 'crates/latent-blobs/src/s3/'], check=True)
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
    print('original HTTP, local storage, provider and S3 source and tests are byte-identical')


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
    expected_local = declared('crates/latent-blobs/src/local/tests.rs', 'local::tests::')
    for name in ('capacities', 'durable', 'failures', 'security'):
        expected_local |= declared('crates/latent-blobs/src/local/tests/' + name + '.rs', 'local::tests::' + name + '::')
    expected_s3 = declared('crates/latent-blobs/src/s3/inventory/tests.rs', 's3::inventory::tests::')
    for name in ('signing', 'xml'):
        expected_s3 |= declared('crates/latent-blobs/src/s3/' + name + '.rs', 's3::' + name + '::tests::')
    assert len(expected_local) == 29 and len(expected_s3) == 7
    actual_local = listed(REPORTS / 'local-list.txt')
    actual_facade = listed(REPORTS / 'blobs-list.txt')
    actual_commit = listed(REPORTS / 'commit-list.txt')
    new_control = 'local_facade_type_tests::local_facade_reexports_the_original_custody_types'
    assert actual_local == expected_local, ('local inventory mismatch', sorted(expected_local - actual_local), sorted(actual_local - expected_local))
    assert actual_facade == expected_s3 | {new_control}, ('S3 inventory mismatch', sorted(expected_s3 - actual_facade), sorted(actual_facade - expected_s3 - {new_control}))
    assert len(actual_commit) == 118, ('commit inventory count', len(actual_commit))
    print('actual discovery: 29 original local, seven original S3, one facade type-identity, 118 commit tests')


if __name__ == '__main__':
    if sys.argv[1:] == ['graph']:
        check_graph()
    elif sys.argv[1:] == ['inventory']:
        check_inventory()
    else:
        raise SystemExit('expected graph or inventory')

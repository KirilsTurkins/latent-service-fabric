"""Exact integrated tree, suite and security-owner checks for #396."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = '82f6392b64122bf38a88bfa1e5debc1aad504a7f'
PARENTS = ['7a256b9ed60362888706aca72361d02b9ba729db', 'b596cf7587d22130fe9ca69305f761428ed88a39']
REPORTS = ROOT / 'custody-integrated-report'
sys.path.insert(0, str(ROOT))


def tree():
    parent = subprocess.check_output(['git', 'rev-parse', 'HEAD^'], text=True).strip()
    assert parent == PRODUCT
    parents = subprocess.check_output(['git', 'show', '-s', '--format=%P', parent], text=True).split()
    assert parents == PARENTS, parents
    paths = subprocess.check_output(['git', 'diff', '--name-only', parent, 'HEAD'], text=True).splitlines()
    assert sorted(paths) == sorted(['.github/workflows/phase4-396-integrated-diagnostic.yml',
                                   'tools/phase4_396_integrated_check.py',
                                   'crates/latent-blobs/tests/phase4-custody-provenance.rs'])
    print('exact integrated merge and three diagnostic-only paths authenticated')


def selections():
    from tools import ci_suite_inventory as registry
    from tools import ci_suite_discovery as discovery
    from tools.phase3_security_artifacts import SecurityError, validate_selection
    from tools.phase3_security_cases import GROUPS
    data = registry.load(ROOT / 'tools/ci/suites.json')
    suite, = [s for s in data['suites'] if s['id'] == 'latent-local-blobs.lib.latent-local-blobs']
    group, = [g for g in GROUPS if g.key == 'blob-storage']
    lines = (REPORTS / 'local-list.txt').read_text(encoding='utf-8').splitlines()
    actual = [line.removesuffix(': test') for line in lines if line.endswith(': test')]
    assert len(actual) == len(set(actual)) == 29
    actual = frozenset(actual)
    assert set(suite['requiredCases']) == set(actual)
    assert suite['manifest'] == group.manifest == 'crates/latent-local-blobs/Cargo.toml'
    assert suite['target'] == group.target == 'latent_local_blobs' and len(group.cases) == 8
    discovery.validate_cases(suite, actual, frozenset(), data['selections'])
    validate_selection(group, actual, frozenset())
    for selector in (lambda: discovery.validate_cases(suite, actual - {next(iter(actual))}, frozenset(), data['selections']),
                     lambda: validate_selection(group, actual - {group.cases[0].name}, frozenset())):
        try:
            selector()
        except (registry.InventoryError, SecurityError):
            pass
        else:
            raise AssertionError('missing-case-negative-accepted')
    print('actual 29-case inventory satisfies additive suite and original eight security cases')
    print('missing-case controls refused; no original suite or case was removed')


if __name__ == '__main__':
    if sys.argv[1:] == ['tree']:
        tree()
    elif sys.argv[1:] == ['selections']:
        selections()
    else:
        raise SystemExit('expected tree or selections')

"""One-shot, exact-source repair for PR 1380; never updates the PR branch."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HEAD = "e82a505f78209a60c57a869065e06714d343a23d"
DEVELOPMENT = "0dd0facf0ac9548c41f2d755655fd37e347eefd7"
ANCESTOR = "9fc52a857c4040f2a9e8a8b10e4a5b0e9bc459ca"
ROOT = Path.cwd()


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=120).stdout.decode()


def replace(path, old, new):
    target = ROOT / path
    text = target.read_text()
    if text.count(old) != 1:
        raise RuntimeError("nonunique-repair-anchor:" + path)
    target.write_text(text.replace(old, new), newline="\n")


def write_json(path, value):
    (ROOT / path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", newline="\n")


def merged(base, ours, theirs, trail=()):
    if ours == theirs or theirs == base:
        return copy.deepcopy(ours)
    if ours == base:
        return copy.deepcopy(theirs)
    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        if not set(base) <= set(ours) & set(theirs):
            raise RuntimeError("unexpected-contract-removal:" + str(trail))
        result = {}
        for key in dict.fromkeys([*ours, *theirs]):
            if key not in base:
                if key in ours and key in theirs and ours[key] != theirs[key]:
                    raise RuntimeError("different-added-contract:" + str((*trail, key)))
                result[key] = copy.deepcopy(ours[key] if key in ours else theirs[key])
            else:
                result[key] = merged(base[key], ours[key], theirs[key], (*trail, key))
        return result
    if trail == ("suites",):
        rows = [{row["id"]: row for row in values} for values in (base, ours, theirs)]
        for values, keyed in zip((base, ours, theirs), rows):
            if len(values) != len(keyed):
                raise RuntimeError("duplicate-suite")
        combined = merged(*rows, trail=trail)
        return list(combined.values())
    if (trail[-1:] == ("expectedCases",) and isinstance(base, list)
            and all(isinstance(x, str) for x in [*base, *ours, *theirs])):
        if not set(base) <= set(ours) & set(theirs):
            raise RuntimeError("unexpected-case-removal")
        return sorted(set(ours) | set(theirs))
    if trail[-1:] == ("minimumCases",) and all(type(x) is int for x in (base, ours, theirs)):
        if min(ours, theirs) < base:
            raise RuntimeError("lowered-test-floor")
        return ours + theirs - base
    raise RuntimeError("unreviewed-merge-conflict:" + str(trail))


assert git("rev-parse", "HEAD").strip() == HEAD
assert git("merge-base", HEAD, DEVELOPMENT).strip() == ANCESTOR
subprocess.run(["git", "merge", "--no-commit", "--no-ff", DEVELOPMENT], check=False, timeout=120)
assert git("rev-parse", "MERGE_HEAD").strip() == DEVELOPMENT
conflicts = set(git("diff", "--name-only", "--diff-filter=U").splitlines())
assert conflicts <= {"tools/build_snapshot.py", "tools/ci/suites.json"}, conflicts
# Preserve upstream's measured, tighter 73 MiB extraction / 80 MiB transport caps.
git("checkout", DEVELOPMENT, "--", "tools/build_snapshot.py")
path = "tools/ci/suites.json"
base, ours, theirs = [json.loads(git("show", ref + ":" + path)) for ref in (ANCESTOR, HEAD, DEVELOPMENT)]
registry = merged(base, ours, theirs)
wire = next(row for row in registry["suites"] if row["id"] == "latent-wire.lib.latent-wire")
added = ["management::errors::audit_tests::" + case for case in (
    "audit_reasons_survive_management_without_private_fields_or_dispositions",
    "unknown_audit_reasons_and_missing_reasons_are_not_public_diagnostics",
    "audit_details_preserve_ambiguous_status_and_independent_committed_receipt",
    "audit_details_obey_source_allocation_and_aggregate_response_bounds",
)]
assert not set(added) & set(wire["expectedCases"])
wire["expectedCases"] = sorted([*wire["expectedCases"], *added])
wire["minimumCases"] += len(added)
for row in registry["suites"]:
    if row["mode"] == "libtest":
        assert row["minimumCases"] == len(row["expectedCases"]), row["id"]
write_json(path, registry)
git("add", "tools/build_snapshot.py", path)
assert not git("diff", "--name-only", "--diff-filter=U").strip()

path = "tools/tests/test_build_source_capacity.py"
replace(path, 'self.assertEqual(limits.max_total_bytes, 80 * 1024 * 1024)',
        'self.assertEqual(limits.max_total_bytes, 73 * 1024 * 1024)')
replace(path, '                self.assertEqual(sum(row["size"] for row in rows), selected_bytes)', '''                # git archive applies the committed eol=crlf attribute to the
                # Windows launcher; ls-tree reports its canonical LF blob size.
                # Account for that one declared conversion, not a tolerance that
                # could conceal a missing input or an unrelated byte change.
                from tools.build_process import run_bounded
                from tools.build_snapshot import git_environment
                launcher = "tools/intellij.cmd"
                self.assertIn("/tools/intellij.cmd text eol=crlf",
                              git(root, "show", revision + ":.gitattributes").splitlines())
                raw = run_bounded(["git", "show", revision + ":" + launcher],
                    cwd=root, env=git_environment(), timeout_seconds=10,
                    max_output_bytes=16384).stdout
                archived = raw.replace(b"\\r\\n", b"\\n").replace(b"\\n", b"\\r\\n")
                self.assertEqual((captured.root / launcher).read_bytes(), archived)
                expected_sizes = {line.split("\\t", 1)[1]: int(line.split("\\t", 1)[0].split()[-1])
                                  for line in sizes}
                self.assertEqual(expected_sizes[launcher], len(raw))
                expected_sizes[launcher] = len(archived)
                self.assertEqual({row["path"]: row["size"] for row in rows}, expected_sizes)
                self.assertEqual(sum(row["size"] for row in rows),
                                 selected_bytes + len(archived) - len(raw))
                self.assertLessEqual(sum(expected_sizes.values()), limits.max_total_bytes)''')
source_test = '''
    def test_committed_crlf_export_is_charged_as_archived_bytes(self):
        from tools.build_snapshot import SOURCE_ALLOWLIST

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, target = parent / "repo", parent / "target"
            repository(repo)
            (repo / "tools").mkdir()
            (repo / "tools/intellij.cmd").write_bytes(b"@echo off\\nexit /b 0\\n")
            (repo / ".gitattributes").write_text("/tools/intellij.cmd text eol=crlf\\n")
            git(repo, "add", ".")
            git(repo, "commit", "--quiet", "-m", "declared Windows line endings")
            revision = git(repo, "rev-parse", "HEAD")
            sizes = git(repo, "ls-tree", "-r", "-l", revision, "--", *SOURCE_ALLOWLIST).splitlines()
            blob_bytes = sum(int(row.split("\\t", 1)[0].split()[-1]) for row in sizes)
            target.mkdir()
            with capture_source(repo, revision, target,
                                SnapshotLimits(max_total_bytes=blob_bytes + 2)) as captured:
                self.assertEqual((captured.root / "tools/intellij.cmd").read_bytes(),
                                 b"@echo off\\r\\nexit /b 0\\r\\n")
                self.assertEqual(sum(row["size"] for row in json.loads(captured.inventory)), blob_bytes + 2)
            with self.assertRaisesRegex(SnapshotError, "captured source total limit exceeded"):
                with capture_source(repo, revision, target,
                                    SnapshotLimits(max_total_bytes=blob_bytes + 1)):
                    self.fail("the CRLF expansion must consume the original byte allowance")
            self.assertEqual(list(target.iterdir()), [])
'''
replace(path, '\n\nif __name__ == "__main__":', '\n' + source_test + '\n\nif __name__ == "__main__":')

path = "tools/static_audit_lifecycle.py"
receipt_function = '''

def retain_receipt(value, path):
    """Retain the complete bounded campaign, returning a byte-bound reference.

    This is test evidence, not a maintenance receipt or permission to replay.
    No commands, uncertain outcomes, acknowledgements or shutdown observations
    are truncated to fit the parent workflow's independent 64 KiB allowance.
    """
    from tools.phase2_operator_process import bounded_receipt

    require(value.get('schemaVersion') == 'latent.static.audit-lifecycle.qualification.v1'
            and value.get('passed') is True, 'audit-fixture-receipt-not-qualified')
    path = Path(path)
    require(0 < len(path.name) <= 128 and path.name.endswith('.json')
            and all(character in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_'
                    for character in path.name), 'audit-fixture-receipt-name')
    encoded = bounded_receipt(value).encode('utf-8')
    summary = {'schemaVersion': 'latent.static.audit-lifecycle.reference.v1', 'passed': True,
        'receiptFile': path.name, 'receiptSha256': 'sha256:' + hashlib.sha256(encoded).hexdigest(),
        'receiptBytes': len(encoded), 'profile': value['profile'], 'multiDaySoak': value['multiDaySoak'],
        'sealedEpochs': len(value['epochs']), 'nodeShutdowns': len(value['shutdowns']),
        'nextSequence': value['nextSequence'], 'historyComplete': value['historyComplete']}
    require(len(bounded_receipt(summary).encode('utf-8')) <= 1024, 'audit-fixture-reference-bound')
    # Exclusive creation also refuses dangling symlinks. A failed write cannot
    # produce a successful reference or overwrite retained qualification evidence.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
        output.write(encoded)
    return summary
'''
text = (ROOT / path).read_text()
assert 'def retain_receipt(' not in text
(ROOT / path).write_text(text.rstrip() + '\n' + receipt_function, newline='\n')
path = "tools/run_static_site_workflow.py"
replace(path, "            from tools.static_audit_lifecycle import qualify as qualify_audit_lifecycle",
        "            from tools.static_audit_lifecycle import qualify as qualify_audit_lifecycle, retain_receipt")
replace(path, "            lifecycle = qualify_audit_lifecycle(client, args, directory / 'audit-lifecycle', configure)",
        "            lifecycle = qualify_audit_lifecycle(client, args, directory / 'audit-lifecycle', configure)\n"
        "            if getattr(args, 'audit_lifecycle_receipt', None) is not None:\n"
        "                lifecycle = retain_receipt(lifecycle, args.audit_lifecycle_receipt)")
replace(path, "    parser.add_argument('--registry-origin')",
        "    parser.add_argument('--audit-lifecycle-receipt', type=Path,\n"
        "                        help='Exclusive output for complete bounded audit lifecycle evidence')\n"
        "    parser.add_argument('--registry-origin')")

path = "tools/tests/test_static_audit_lifecycle.py"
receipt_tests = '''
    def test_separate_receipt_is_lossless_private_and_keeps_parent_within_original_bound(self):
        import hashlib
        import stat
        from tools.phase2_operator_process import bounded_receipt
        from tools.static_audit_lifecycle import retain_receipt

        report = {'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1', 'passed': True,
            'profile': 'linux-signed-static-32-records-30-second-proof-age', 'multiDaySoak': False,
            'epochs': ['first', 'second'], 'shutdowns': [{'reaped': True}] * 3,
            'nextSequence': '71', 'historyComplete': False,
            'commands': [{'argv': ['web', 'renew-evidence'], 'outcomeKnown': False,
                          'auditAck': {'status': 'OutcomeUnknown'}, 'receiptDigest': None}],
            'boundedFixtureEvidence': 'x' * 60000}
        with self.assertRaisesRegex(WorkflowError, 'receipt-byte-bound'):
            bounded_receipt({'existingEvidence': 'y' * 55000, 'auditLifecycle': report})
        path = self.root / 'audit-lifecycle-receipt.json'
        reference = retain_receipt(report, path)
        raw = path.read_bytes()
        self.assertEqual(json.loads(raw), report)
        self.assertEqual(reference['receiptSha256'], 'sha256:' + hashlib.sha256(raw).hexdigest())
        self.assertEqual(reference['receiptBytes'], len(raw))
        self.assertEqual(reference['receiptFile'], path.name)
        self.assertNotIn(str(self.root), json.dumps(reference))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertLessEqual(len(raw), 65536)
        self.assertLessEqual(len(bounded_receipt(reference).encode()), 1024)
        self.assertLessEqual(len(bounded_receipt({'existingEvidence': 'y' * 55000,
                                                'auditLifecycle': reference}).encode()), 65536)
        self.assertIs(json.loads(raw)['commands'][0]['outcomeKnown'], False)

    def test_separate_receipt_refuses_oversize_and_unqualified_reports_before_creation(self):
        from tools.static_audit_lifecycle import retain_receipt

        path = self.root / 'audit-lifecycle-receipt.json'
        for value, reason in (
            ({'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1',
              'passed': True, 'payload': '\\u00e9' * 40000}, 'receipt-byte-bound'),
            ({'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1',
              'passed': False}, 'receipt-not-qualified'),
            ({'schemaVersion': 'wrong', 'passed': True}, 'receipt-not-qualified'),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(WorkflowError, reason):
                retain_receipt(value, path)
            self.assertFalse(path.exists())

    def test_separate_receipt_never_overwrites_existing_or_linked_evidence(self):
        from tools.static_audit_lifecycle import retain_receipt

        value = {'schemaVersion': 'latent.static.audit-lifecycle.qualification.v1', 'passed': True,
            'profile': 'controlled-fixture', 'multiDaySoak': False, 'epochs': [], 'shutdowns': [],
            'nextSequence': '1', 'historyComplete': False}
        original = self.record('original.json', b'original-evidence')
        alias = self.root / 'linked.json'
        alias.symlink_to(original)
        dangling = self.root / 'dangling.json'
        dangling.symlink_to(self.root / 'absent.json')
        for path in (original, alias, dangling):
            with self.subTest(path=path.name), self.assertRaises(FileExistsError):
                retain_receipt(value, path)
        self.assertEqual(original.read_bytes(), b'original-evidence')
        self.assertTrue(alias.is_symlink() and dangling.is_symlink())
        self.assertFalse((self.root / 'absent.json').exists())
'''
replace(path, "\n\nif __name__ == '__main__':", '\n' + receipt_tests + "\n\nif __name__ == '__main__':")

old = '--chrome "$(command -v google-chrome)" > "${RUNNER_TEMP}/phase2-gate/static-site-receipt.json"'
new = '--chrome "$(command -v google-chrome)" --audit-lifecycle-receipt "${RUNNER_TEMP}/phase2-gate/audit-lifecycle-receipt.json" > "${RUNNER_TEMP}/phase2-gate/static-site-receipt.json"'
replace('.github/workflows/ci.yml', old, new)
path = 'tools/ci/contracts/workflows/ci.yml/jobs/rust.json'
contract = json.loads((ROOT / path).read_text())
step = next(step for step in contract['definition']['steps'] if step.get('name') ==
            'Qualify signed static sites through OCI and actual browsers')
assert step['run'].count(old) == 1
step['run'] = step['run'].replace(old, new)
key = '.github/workflows/ci.yml:rust:Qualify signed static sites through OCI and actual browsers'
for row in contract['coverage'].values():
    if row['after'] == key:
        row['disposition'] = 'extended'
contract['reviewReason'] += ' Preserve every publication/browser/negative-control command and execution guard; retain the complete audit campaign in a second independently bounded 64 KiB artifact instead of overflowing the aggregate receipt.'
write_json(path, contract)
# Preserve the immutable historical command floor; approve only this exact extra output argument.
replace('tools/tests/test_ci_contracts.py',
        '            elif key != reviewed_extension and key not in performance_extensions:',
        '            elif key == ' + repr(key) + ':\n'
        '                old = ' + repr(old) + '\n'
        '                new = ' + repr(new) + '\n'
        '                self.assertEqual(value["run"].count(old), 1)\n'
        '                self.assertEqual(data["after"][key], dict(value, run=value["run"].replace(old, new)), key)\n'
        '            elif key != reviewed_extension and key not in performance_extensions:')

path = 'docs/operations/audit-journal-lifecycle.md'
replace(path, '## Qualification boundary\n', '''## Qualification boundary

The publications lane retains `audit-lifecycle-receipt.json` with the complete
campaign commands, outcomes, acknowledgements, epoch and shutdown observations.
`static-site-receipt.json` contains a small reference binding its exact filename,
SHA-256 digest and byte length. Each receipt retains an independent 64 KiB limit;
no observation is truncated to fit the parent workflow. The explicit
`--audit-lifecycle-receipt` output refuses existing files and symlinks. These are
qualification observations, not maintenance authority or permission to replay.
''')

# Propose only reviewed changed fragments; existing case guards must be identical.
sys.path.insert(0, str(ROOT))
from tools import ci_contracts
for kind, source, reason in (
    ('owner', 'tools/run_static_site_workflow.py',
     'Preserve all native and browser assertions and original deadlines; add exclusive separately bounded audit evidence output and digest-linked parent reference.'),
    ('python', 'tools/tests/test_build_source_capacity.py',
     'Preserve every existing test and execution guard; reconcile the upstream 73 MiB source cap and exactly charge the committed Windows CRLF archive conversion, including a one-byte overflow fixture.'),
    ('python', 'tools/tests/test_static_audit_lifecycle.py',
     'Preserve every live-campaign helper assertion and execution guard; add unconditional lossless evidence split, original byte bounds, unknown outcome preservation and no-overwrite regressions.'),
    ('python', 'tools/tests/test_ci_contracts.py',
     'Preserve the immutable history and every existing execution guard; allow only the exact additional audit receipt output argument on the unchanged mandatory publications command.'),
):
    output = ROOT / 'target/ci/proposals/audit-1380' / kind / Path(source).stem
    proposed = ci_contracts.propose(ROOT, kind, source, None, output, reason)
    destination = ROOT / ci_contracts.DIRECTORY / proposed.relative_to(output)
    destination.write_bytes(proposed.read_bytes())

allowed = {
    '.github/workflows/ci.yml', 'tools/build_snapshot.py', 'tools/ci/suites.json',
    'tools/static_audit_lifecycle.py', 'tools/run_static_site_workflow.py',
    'tools/tests/test_build_source_capacity.py', 'tools/tests/test_static_audit_lifecycle.py',
    'tools/tests/test_ci_contracts.py', 'docs/operations/audit-journal-lifecycle.md',
    'tools/ci/contracts/workflows/ci.yml/jobs/rust.json',
    'tools/ci/contracts/owners/tools/run_static_site_workflow.py.json',
    'tools/ci/contracts/python/test_build_source_capacity.py.json',
    'tools/ci/contracts/python/test_static_audit_lifecycle.py.json',
    'tools/ci/contracts/python/test_ci_contracts.py.json',
}
# Unstaged changes are only the explicit repairs; the merge's other staged paths
# are Git's unchanged upstream/feature integration, never copied from a stale tree.
assert set(git('diff', '--name-only').splitlines()) <= allowed
assert not git('ls-files', '--others', '--exclude-standard').strip()
git('add', *sorted(allowed))
git('diff', '--cached', '--check')
git('commit', '-m', 'fix(audit): merge development and repair lifecycle CI evidence and discovery')
print('REPAIR_CANDIDATE=' + git('rev-parse', 'HEAD').strip(), flush=True)
print('REPAIR_TREE=' + git('rev-parse', 'HEAD^{tree}').strip(), flush=True)

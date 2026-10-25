"""Prepare only the reviewed inventory consumers on the exact PR 1380 head."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path.cwd()
HEAD = 'f1dd3bc1c6ed68d2b4e5a0ed0c75d8bcf3e7f588'

def git(*args):
    return subprocess.check_output(['git', *args], text=True, timeout=120).strip()

def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    assert text.count(old) == 1, (path, old)
    file.write_text(text.replace(old, new), newline='\n')

assert git('rev-parse', 'HEAD') == HEAD
assert not git('status', '--porcelain')
startup = 'apps/latentd/tests/standalone_node/startup.rs'
replace(startup, 'assert_eq!(inventory.topology.entries.len(), 25);',
        'assert_eq!(inventory.topology.entries.len(), 26);\n            assert_audit_topology(&inventory.topology.entries);')
replace(startup, '\nfn assert_catalog_topology(', '''
fn assert_audit_topology(entries: &[NodeTopologyEntry]) {
    let mut matching = entries.iter().filter(|row| row.name == "audit-journal");
    let row = matching.next().expect("explicit audit configuration observation");
    assert!(matching.next().is_none(), "duplicate audit row");
    assert_eq!(row.kind, "store");
    assert_eq!(row.ownership, ResourceOwnership::NodeFixed);
    // This fixture does not configure audit. A row or retained handle is not
    // a measurement of a live worker, including after the second node start.
    assert_eq!((row.configured_count, row.active_count), (0, None));
    assert_eq!(row.attributes.len(), 2);
    assert_eq!(row.attributes.get("profile").map(String::as_str), Some("audit-capacity-v1"));
    assert_eq!(row.attributes.get("measurementStatus").map(String::as_str), Some("not-configured"));
}

fn assert_catalog_topology(''')
profile = 'tools/phase2_gate_resource_profile.py'
replace(profile, 'FIXED_UNKNOWN_ROWS = ("wasmtime-epoch", "grpc-listener")',
        'FIXED_UNKNOWN_ROWS = ("wasmtime-epoch", "grpc-listener", "audit-journal")')
replace(profile, '            # These two native inventory sources intentionally expose no live',
        '            # These native inventory sources intentionally expose no live')
replace(profile, '    for runtime, stack in zip(FIXED_RUNTIME_ROWS, FIXED_STACK_ROWS):', '''    # The configured journal exposes capacity, not a live-worker count. Keep
    # the new row explicit without accepting arbitrary topology additions or
    # changing the frozen workload's audit limits. Shutdown still verifies the
    # actual worker join independently; None must never become zero or one.
    audit = rows["audit-journal"]
    attributes = audit["attributes"]
    require(audit["kind"] == "store" and isinstance(attributes, dict)
            and attributes.get("profile") == "audit-capacity-v1"
            and attributes.get("measurementStatus") == "available", "inventory-audit-profile")
    configured_audit = configuration("tests")["audit"]
    for observed, configured in (("maximumRecords", "records"), ("maximumDiskBytes", "diskBytes"),
                                 ("maximumQueuedOperations", "queuedOperations"),
                                 ("maximumQueryOwners", "queryOwners")):
        require(integer(attributes.get(observed)) == configured_audit[configured],
                "inventory-audit-profile")
    for runtime, stack in zip(FIXED_RUNTIME_ROWS, FIXED_STACK_ROWS):''')
tests = 'tools/tests/test_phase2_gate_resource.py'
replace(tests, '    warm = phase in ("baseline", "dormant")', '''    audit = next(row for row in rows if row["name"] == "audit-journal")
    audit.update(kind="store", attributes={
        "profile": "audit-capacity-v1", "measurementStatus": "available",
        "maximumRecords": "512", "maximumDiskBytes": "8388608",
        "maximumQueuedOperations": "8", "maximumQueryOwners": "2",
    })
    warm = phase in ("baseline", "dormant")''')
replace(tests, 'for missing in ("wasmtime-compiler", "publication-catalog"):',
        'for missing in ("wasmtime-compiler", "publication-catalog", "audit-journal"):')
replace(tests, 'class Phase2ResourceTests(unittest.TestCase):', '''class Phase2ResourceTests(unittest.TestCase):
    def test_audit_capacity_row_preserves_unknown_liveness_and_frozen_limits(self):
        value = complete_receipt()
        original = copy.deepcopy(value)
        validate_receipt(value)
        self.assertEqual(value, original)
        for field, bad in (("kind", "thread"), ("ownership", "activation-scoped"),
                           ("configuredCount", "0"), ("configuredCount", "2"),
                           ("activeCount", "0"), ("activeCount", "1")):
            inventory = complete_inventory()
            row = next(row for row in inventory["topology"]["entries"] if row["name"] == "audit-journal")
            row[field] = bad
            with self.subTest(field=field, value=bad), self.assertRaises(WorkflowError):
                quiet(inventory)
        for field, bad in (("profile", "unknown"), ("measurementStatus", "not-configured"),
                           ("maximumRecords", "513"), ("maximumDiskBytes", "8388609"),
                           ("maximumQueuedOperations", "9"), ("maximumQueryOwners", "3"),
                           ("maximumRecords", None), ("maximumRecords", True)):
            inventory = complete_inventory()
            row = next(row for row in inventory["topology"]["entries"] if row["name"] == "audit-journal")
            row["attributes"][field] = bad
            with self.subTest(field=field, value=bad), self.assertRaises(WorkflowError):
                quiet(inventory)

    def test_audit_topology_addition_does_not_admit_duplicate_or_arbitrary_rows(self):
        for name, reason in (("audit-journal", "inventory-duplicate-row"),
                             ("unreviewed-owner", "inventory-fixed-rows")):
            inventory = complete_inventory()
            row = copy.deepcopy(next(row for row in inventory["topology"]["entries"]
                                     if row["name"] == "audit-journal"))
            row["name"] = name
            inventory["topology"]["entries"].append(row)
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, reason):
                quiet(inventory)
''')
sys.path.insert(0, str(ROOT))
from tools import ci_contracts
contract = ROOT / 'tools/ci/contracts/python/test_phase2_gate_resource.py.json'
before = json.loads(contract.read_text())
output = ROOT / 'target/ci/proposals/audit-inventory'
proposed = ci_contracts.propose(ROOT, 'python', tests, None, output,
    'Retain every existing case and workload/OS/receipt bound. Extend the shared fixture with the actual audit-capacity-v1 row, require unchanged configured audit limits and unknown worker liveness, and reject duplicate, missing and arbitrary rows. No execution or skip guard is weakened.')
after = json.loads(proposed.read_text())
assert set(before['cases']) <= set(after['cases'])
for case in before['cases']:
    def guard(record):
        value = record['guards'][case]
        return record.get('guardDefinitions', {}).get(value, value) if isinstance(value, str) else value
    old, new = guard(before), guard(after)
    assert {k:v for k,v in old.items() if k != 'fixtureGuards'} == {k:v for k,v in new.items() if k != 'fixtureGuards'}, case
contract.write_bytes(proposed.read_bytes())
allowed = {startup, profile, tests, str(contract.relative_to(ROOT))}
assert set(git('diff', '--name-only').splitlines()) == allowed
assert not git('ls-files', '--others', '--exclude-standard')
print('Prepared four reviewed inventory-consumer files', flush=True)

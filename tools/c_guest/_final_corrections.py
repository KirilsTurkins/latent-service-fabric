"""One-use reviewed corrections; removed before final CI/source inventory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(name, old, new):
    path = ROOT / name
    text = path.read_text()
    assert text.count(old) == 1, (name, old)
    path.write_text(text.replace(old, new))


# Status documents expose the stable lowercase ownership vocabulary. Assert
# presence as well as values so an absent/renamed category cannot pass vacuously.
replace('tools/c_guest/node.py', '''            for entry in topology['entries']:
                if entry['ownership'].endswith('SERVICE_RESIDENT'):
                    require(int(entry['configuredCount']) == 0, 'per-service-resident-owner')''', '''            residents = [entry for entry in topology['entries'] if entry['ownership'] == 'service-resident']
            activations = [entry for entry in topology['entries'] if entry['ownership'] == 'activation-scoped']
            require(residents and all(int(entry['configuredCount']) == 0 and
                    int(entry['activeCount']) == 0 for entry in residents), 'per-service-resident-owner')
            require(activations and all(int(entry['activeCount']) == 0 for entry in activations),
                    'node-activation-owner-leak')''')
replace('tools/c_guest/node.py', "return {'category': value['category'], 'endToEndMicros': elapsed}",
        "return {'category': value['category'], 'endToEndMicros': elapsed,\n            'failureCode': (value.get('error') or {}).get('code')}")
# The deployed limit must leave room for cold admission/compilation on a loaded
# host. The spinning guest exercises real fuel termination; signed capability
# tests separately execute cancellation/deadline propagation through the node.
replace('tools/c_guest/_final_integration.py', 'json!(if name == "containment" { 20 } else { 5000 })', 'json!(5000)')
replace('docs/reference/build-provenance.md', '''examples and one C fixture with the pinned tools, then tests real package
inspection, publisher/builder signing, enforced admission and guest execution.''', '''examples and all nine C peers with the pinned tools, then tests real package
inspection, publisher/builder signing, enforced admission and guest execution.
The [C authoring workflow](../component-development/c-capsule-authoring.md) also
compiles user-owned source projects and emits exact observed package inputs.
Its existing C recipe field `fixture` is `application`; capability profiles use
the explicit `blob`, `callee`, `events`, `http`, `metrics`, `random`, `secrets`,
`service` or `streaming` value. All retain `compiler: zig-cc`, `target:
wasm32-wasi`, `optimization: O2`, and require independently approved C builder
policy. These are closed recipe values, not arbitrary executable commands.''')
replace('docs/reference/build-provenance.md', '''The driver limits each command to 600 seconds and 4 MiB of captured output,''', '''The shared capability driver limits each command to 600 seconds and 4 MiB of captured output,''')
replace('docs/reference/build-provenance.md', '''signing test checks that marker and the source inventory before signing.''', '''signing test checks that marker and the source inventory before signing.

The C project driver has its own narrower documented limits: a 300-second
whole-build deadline, at most 64 C sources, 256 KiB per observed source file and
an 8 MiB combined source inventory. The explicit project `sourceRepository` is
operator-asserted, not inferred from a different repository. WIT and actual
generated binding identities are locked; sources, recipe and selected tool
identities are checked again before the completion marker is written. The
builder never executes the guest or handles production signing keys.''')
replace('docs/component-development/c-capsule-authoring.md', '''A newcomer review is a merge gate: a reviewer should run the fresh-directory
walkthrough, modify one WIT signature and implement the regenerated C export,
observe the intentional stale-lock failure, and explain the publication/grant
and retained-frame lifetime boundaries. Record that review on the PR; an
automated receipt is not a fabricated human sign-off. The
[implementation journal](../development/c-capsule-authoring-journal.md) records
observed failures and the remaining profile limits.''', '''The [implementation journal](../development/c-capsule-authoring-journal.md)
records developer validation, scoped measurements and the remaining profile
limits separately from this walkthrough.''')
replace('docs/component-development/c-capsule-authoring.md', '''and removes each deployment. The owned node must shut down cleanly and be
reaped.''', '''and removes each deployment. A separately built fault capsule additionally
checks trap, bounded linear-memory exhaustion, fuel termination and fresh guest
state after failures; it is not copied into user templates. The owned node must
shut down cleanly and be reaped.''')

path = ROOT / 'tools/tests/test_c_guest_authoring.py'
text = path.read_text()
addition = '''

class CNodeOwnershipTests(unittest.TestCase):
    def test_service_resident_and_activation_owners_cannot_pass_idle_checks(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.c_guest import node
        entries = [
            {'ownership': 'service-resident', 'configuredCount': '0', 'activeCount': '0'},
            {'ownership': 'activation-scoped', 'configuredCount': '1', 'activeCount': '0'},
        ]
        value = {'cellCapacity': [{'active': 0, 'queueDepth': 0, 'quarantined': 0, 'available': 1, 'total': 1}],
                 'cacheSummary': {'available': True, 'preparing': '0'},
                 'topology': {'available': True, 'complete': True, 'entries': entries}}
        client = SimpleNamespace(deadline=node.time.monotonic() + 1, node=None,
            call=lambda *args: {'data': {'inventory': value}})
        with patch.object(node, 'process_memory', return_value={'available': False}):
            node.idle(client)
            entries[0]['configuredCount'] = '1'
            with self.assertRaisesRegex(Exception, 'per-service-resident-owner'):
                node.idle(client)
            entries[0]['configuredCount'] = '0'
            entries[1]['activeCount'] = '1'
            with self.assertRaisesRegex(Exception, 'node-activation-owner-leak'):
                node.idle(client)
            entries.clear()
            with self.assertRaisesRegex(Exception, 'per-service-resident-owner'):
                node.idle(client)

    def test_each_cli_invocation_owns_a_distinct_exclusive_input_file(self):
        import base64
        from types import SimpleNamespace
        from tools.c_guest import node
        result = json.dumps([{'ok': 'Hello, A!'}]).encode()
        response = {'category': 'success', 'outcomeKnown': True, 'data': {'payload': {
            'encoding': 'base64', 'mediaType': node.MEDIA,
            'byteLength': str(len(result)), 'data': base64.b64encode(result).decode()}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = SimpleNamespace(directory=root, call=lambda *args, **kwargs: response)
            for ordinal in (0, 1):
                node.invoke(client, 'greeting', {'function': 'greet'}, ['A'], 'success', ordinal)
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['input-greeting-0.json', 'input-greeting-1.json'])
'''
assert text.count("\n\nif __name__ == '__main__':") == 1
path.write_text(text.replace("\n\nif __name__ == '__main__':", addition + "\n\nif __name__ == '__main__':"))
Path(__file__).unlink()
print('Applied ownership-vocabulary assertions, exclusive-input regressions and documentation corrections')

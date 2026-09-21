"""Required commands cannot disappear behind a successful small suite."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_coverage as coverage, ci_suite_inventory as registry


class CoverageTests(unittest.TestCase):
    def test_reviewed_coverage_map_matches_current_commands_and_owners(self):
        data = coverage.validate()
        self.assertGreater(len(data['before']), 80)
        self.assertEqual(set(data['before']), set(data['coverage']))
        for token in ('--doc --locked', 'ed25519-dalek/legacy_compatibility', '--profile smoke',
                      'run_catalog_scale', 'tools/validate_contracts.sh'):
            self.assertIn(token, json.dumps(data['after']))

    def test_new_removed_or_modified_workflow_command_is_rejected(self):
        valid = coverage.commands(registry.ROOT)
        for action in ('add', 'remove', 'change'):
            changed = copy.deepcopy(valid)
            key = next(iter(changed))
            if action == 'add': changed['unregistered'] = changed[key]
            if action == 'remove': del changed[key]
            if action == 'change': changed[key]['run'] = 'true'
            with self.subTest(action=action), patch.object(coverage, 'commands', return_value=changed), self.assertRaises(ValueError):
                coverage.validate()

    def test_changed_nested_owner_requires_explicit_inventory_review(self):
        with patch.object(coverage, 'delegated_owners', return_value={}), self.assertRaises(ValueError):
            coverage.validate()

    def test_no_coverage_row_may_remove_an_existing_required_owner(self):
        data = registry.read_json(coverage.INVENTORY)
        row = next(iter(data['coverage'].values())); row['after'] = 'removed'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'commands.json'; path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): coverage.validate(inventory=path)

    def test_duplicate_required_step_identity_fails_closed(self):
        document = 'jobs:\n  test:\n    steps:\n      - name: same\n        run: true\n      - name: same\n        run: false\n'
        with self.assertRaises((ValueError, AttributeError)):
            coverage.workflow_commands('ci.yml', document)

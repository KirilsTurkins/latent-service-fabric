"""Reject stale profiles and incomplete roles before any AOT preparation command."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import aot_test_inputs as inputs
from tools.tests import test_aot_test_inputs as fixtures


class AotProfileBoundaries(unittest.TestCase):
    def test_previous_profile_is_rejected_before_any_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            manifest = root / 'manifest.json'
            for previous in ('debug-all-features-v9', 'debug-all-features-v11'):
                with self.subTest(profile=previous):
                    manifest.write_text(json.dumps({'schema': inputs.SCHEMA, 'profile': previous}))
                    with mock.patch.object(inputs.artifacts, 'run_owned') as command:
                        with self.assertRaisesRegex(inputs.InputError, 'wrong-input-schema-or-profile'):
                            inputs.validate(root, manifest)
                        command.assert_not_called()

    def test_missing_go_witness_feature_rejects_every_prepared_role(self):
        # Reuse the maintained inventory fixture without duplicating its tests.
        fixture = fixtures.PreparedInputsTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        baseline = json.loads(json.dumps(fixture.records))
        for index, record in enumerate(baseline[:-1]):
            for feature in ('development-go-network-read-witness', 'development-go-lazy-owner-observer'):
                with self.subTest(target=record['target']['name'], feature=feature):
                    fixture.records = json.loads(json.dumps(baseline))
                    fixture.records[index]['features'].remove(feature)
                    fixture.write_inventory()
                    with self.assertRaisesRegex(inputs.InputError, 'incompatible-cargo-feature-sets'):
                        inputs.inventory_inputs(fixture.inventory, fixture.repo)
                    self.assertFalse(fixture.output.exists())

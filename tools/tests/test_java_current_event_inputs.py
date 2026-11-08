"""Signed Java event source inputs constrain packaging and never grant authority."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_schema import SOURCE, create
from tools.rust_capsule_project import read_file, read_json, snapshot
from tools.transaction_guest_project import CURRENT_EVENT_PROFILE, EVENT_REQUIREMENTS, package_effect_requirements


class CurrentJavaEventInputs(unittest.TestCase):
    def test_explicit_native_profile_is_carried_without_changing_guest_intent(self):
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = create(root / 'plain', 'legacy-v1')
            project = create(root / 'current', 'legacy-v1', event_profile=profile)
            files = snapshot(project)
            self.assertEqual(read_file(project / SOURCE), read_file(plain / SOURCE))
            self.assertIn(b'new Intent("approved-event", "event", payload)', files[SOURCE])
            self.assertNotIn(EVENT_REQUIREMENTS, snapshot(plain))
            requirements = read_json(project / EVENT_REQUIREMENTS)
            self.assertEqual(requirements['idempotencyProfile'], profile)
            self.assertEqual(requirements['operation'], 'event')
            self.assertEqual(requirements['protocol'], 'lsf-jetstream-event-v1')
            output = root / 'package'
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, read_json(project / 'capsule-project.json'), files),
                             (EVENT_REQUIREMENTS, 'asset', 'application/json'))
            self.assertEqual((output / EVENT_REQUIREMENTS).read_bytes(), files[EVENT_REQUIREMENTS])

    def test_packaging_refuses_changed_identity_missing_marker_and_ambiguous_effects(self):
        profile = 'js-window-v1:' + 'b' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'current', 'writer-v2', event_profile=profile)
            original = snapshot(project)
            model = read_json(project / 'capsule-project.json')
            changes = []
            missing = dict(original)
            del missing[CURRENT_EVENT_PROFILE]
            changes.append(missing)
            altered = dict(original)
            value = json.loads(altered[EVENT_REQUIREMENTS])
            value['idempotencyProfile'] = 'js-window-v1:' + 'c' * 64
            altered[EVENT_REQUIREMENTS] = json.dumps(value).encode()
            changes.append(altered)
            ambiguous = dict(original)
            ambiguous['deferred-http-requirements.json'] = b'{}'
            changes.append(ambiguous)
            for index, files in enumerate(changes):
                output = root / ('bad-' + str(index))
                output.mkdir()
                with self.assertRaises(ValueError):
                    package_effect_requirements(output, model, files)
                self.assertFalse((output / EVENT_REQUIREMENTS).exists())
            for bad in ('js-window-v1:' + 'A' * 64, 'qualified-http-v1:' + 'a' * 64, '', 7):
                with self.assertRaises(ValueError):
                    create(root / ('bad-profile-' + str(len(str(bad)))), 'legacy-v1', event_profile=bad)
            with self.assertRaises(ValueError):
                create(root / 'mixed', 'legacy-v1', effect='put-once', event_profile=profile)


if __name__ == '__main__':
    unittest.main()

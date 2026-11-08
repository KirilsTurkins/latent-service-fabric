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
            from tools.java_transaction_qualification.packaging import schema_assets
            self.assertEqual(schema_assets(files)[CURRENT_EVENT_PROFILE], files[CURRENT_EVENT_PROFILE])
            from types import SimpleNamespace
            from tools.java_transaction_qualification.inputs import digest
            from tools.java_transaction_qualification.packaging import captured_assets
            item = SimpleNamespace(name="aggregate", requirements_digest=None,
                                   event_requirements_digest=digest(files[EVENT_REQUIREMENTS]))
            self.assertEqual(captured_assets(item, files)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            with self.assertRaises(ValueError):
                captured_assets(SimpleNamespace(name="aggregate", requirements_digest=None,
                                                event_requirements_digest="sha256:" + "0" * 64), files)
            without_marker = dict(files)
            del without_marker[CURRENT_EVENT_PROFILE]
            with self.assertRaises(ValueError):
                schema_assets(without_marker)

    def test_compiler_selection_is_exclusive_and_captures_the_profile(self):
        from tools.compile_transaction_guests import authored_project, compile_guests
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = authored_project('java', 'aggregate', root / 'project', java_current_event_profile=profile)
            self.assertEqual(read_json(project / EVENT_REQUIREMENTS)['idempotencyProfile'], profile)
            for language, options in [
                ('rust', {}), ('java', {'java_schema_put_once': True}),
                ('java', {'java_post_stage_diagnostic': True}), ('java', {'java_state_acceptance': True}),
                ('java', {'java_early_http_denial': True}),
                ('java', {'java_current_http_profile': 'qualified-http-v1:' + 'b' * 64}),
            ]:
                target = root / ('invalid-' + str(len(list(root.iterdir()))))
                with self.assertRaises(ValueError):
                    compile_guests(language, target, java_current_event_profile=profile, **options)
                self.assertFalse(target.exists())
            with self.assertRaises(ValueError):
                authored_project('java', 'forbidden-http', root / 'wrong', java_current_event_profile=profile)

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

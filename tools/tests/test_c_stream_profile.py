"""Selection controls for the bounded C IPv4 stream adapter."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule_project
from tools.c_guest import standard_facilities, threading
from tools.c_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, snapshot


class CStreamProfile(unittest.TestCase):
    def test_creation_captures_profile_without_grant_and_requires_threads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'requires-cooperative-threading'):
                c_capsule_project.create(root / 'refused', 'greeting', runtime_profile=standard_facilities.STREAM_PROFILE)
            self.assertFalse((root / 'refused').exists())
            with self.assertRaisesRegex(ValueError, 'template-requires-greeting'):
                c_capsule_project.create(root / 'unsupported-template', 'shipping',
                    runtime_profile=standard_facilities.STREAM_PROFILE, threading_profile=threading.PROFILE)
            self.assertFalse((root / 'unsupported-template').exists())
            project = c_capsule_project.create(root / 'selected', 'greeting',
                runtime_profile=standard_facilities.STREAM_PROFILE, threading_profile=threading.PROFILE)
            files = snapshot(project)
            selected, _, _ = c_capsule_project.validate(files)
            self.assertEqual(selected['runtimeProfile'], standard_facilities.STREAM_PROFILE)
            self.assertEqual(selected['threadingProfile'], threading.PROFILE)
            self.assertIn(b'greet: async func(name: string)', files['wit/world.wit'])
            self.assertIn('vendor/lsf/sdk/c-guest/src/standard-streams.c', files)
            self.assertIn('vendor/lsf/sdk/c-guest/include/lsf/standard-streams.h', files)
            changed = dict(files)
            value = json.loads(changed['capsule-project.json'])
            value.pop('threadingProfile')
            changed['capsule-project.json'] = json.dumps(value).encode()
            with self.assertRaisesRegex(ValueError, 'requires-cooperative-threading'):
                c_capsule_project.validate(changed)
            for missing in ('vendor/lsf/sdk/c-guest/src/standard-streams.c',
                            'vendor/lsf/sdk/c-guest/include/lsf/standard-streams.h',
                            'vendor/lsf/wit/platform/network/package.wit'):
                incomplete = dict(files)
                incomplete.pop(missing)
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'requires-captured-runtime'):
                    c_capsule_project.validate(incomplete)

    def test_compiler_owns_the_selected_symbols_and_refuses_unthreaded_before_generation(self):
        facilities = standard_facilities
        selected = facilities.compiler_defines(facilities.STREAM_PROFILE, ('CUSTOM=1',))
        self.assertEqual(selected, ('CUSTOM=1', 'LSF_C_STREAM_NETWORK=1'))
        for symbol in (*facilities.STREAM_SYMBOLS, 'LSF_C_STREAM_NETWORK', 'POLLPRI',
                       '__lsf_c_net_send', 'LSF_C_STANDARD_STREAMS_H'):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(ValueError, 'compiler-owned-symbol'):
                facilities.compiler_defines(facilities.STREAM_PROFILE, (symbol + '=1',))
        compiler = Compiler.__new__(Compiler)
        with tempfile.TemporaryDirectory() as temporary, patch('tools.c_guest.compiler.generate') as generate:
            output = Path(temporary) / 'no-output'
            with self.assertRaisesRegex(ValueError, 'requires-cooperative-threading'):
                compiler.compile([Path('missing.c')], Path('missing-wit'), 'service', output,
                                 runtime_profile=facilities.STREAM_PROFILE)
            generate.assert_not_called()
            self.assertFalse(output.exists())

    def test_derived_world_imports_only_existing_network_and_standard_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            original = b'package tests:stream@1.0.0; world service { export api; } interface api { run: func(); }\n'
            (source / 'world.wit').write_bytes(original)
            staged = standard_facilities.stage(source, 'service', root / 'derived', ROOT / 'wit/platform',
                                               profile=standard_facilities.STREAM_PROFILE)
            result = (staged / 'world.wit').read_text()
            for name in standard_facilities.PROFILE_IMPORTS[standard_facilities.STREAM_PROFILE]:
                self.assertEqual(result.count('import ' + name + ';'), 1)
            self.assertEqual((source / 'world.wit').read_bytes(), original)
            self.assertNotIn('wasi:', result)


if __name__ == '__main__':
    unittest.main()

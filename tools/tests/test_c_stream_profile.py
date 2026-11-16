"""Selection controls for the bounded C IPv4 stream adapter."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule, c_capsule_project
from tools.c_guest import standard_facilities, threading
from tools.c_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, inventory, snapshot


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
            self.assertEqual(c_capsule.main(['new', str(root / 'cli'), '--threading-profile', threading.PROFILE,
                                             '--runtime-profile', standard_facilities.STREAM_PROFILE]), 0)
            cli_project, _, _ = c_capsule_project.validate(snapshot(root / 'cli'))
            self.assertEqual(cli_project['runtimeProfile'], standard_facilities.STREAM_PROFILE)
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
            combined = c_capsule_project.create(root / 'combined', 'greeting',
                runtime_profile=standard_facilities.STREAM_STDIO_PROFILE, threading_profile=threading.PROFILE)
            combined_files = snapshot(combined)
            combined_value, _, _ = c_capsule_project.validate(combined_files)
            self.assertEqual(combined_value['runtimeProfile'], standard_facilities.STREAM_STDIO_PROFILE)
            self.assertEqual(combined_value['limits']['logBytes'], 0)
            self.assertIn(b'greet: async func(name: string)', combined_files['wit/world.wit'])
            for missing in ('vendor/lsf/sdk/c-guest/src/standard-stdio.c',
                            'vendor/lsf/wit/platform/log/package.wit'):
                incomplete = dict(combined_files)
                incomplete.pop(missing)
                with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'requires-captured-runtime'):
                    c_capsule_project.validate(incomplete)
            # The combined profile resolves its four stdio ABI calls in the
            # core; it need not select the separate preview1 adapter file.
            without_adapter = dict(combined_files)
            without_adapter.pop('vendor/lsf/sdk/c-guest/src/standard-stdio.wat')
            lock = json.loads(without_adapter['sdk-lock.json'])
            vendor = {path.removeprefix('vendor/lsf/'): data for path, data in without_adapter.items()
                      if path.startswith('vendor/lsf/')}
            lock['sdk'] = json.loads(inventory(vendor))
            without_adapter['sdk-lock.json'] = json.dumps(lock).encode()
            c_capsule_project.validate(without_adapter)

    def test_compiler_owns_the_selected_symbols_and_refuses_unthreaded_before_generation(self):
        facilities = standard_facilities
        selected = facilities.compiler_defines(facilities.STREAM_PROFILE, ('CUSTOM=1',))
        self.assertEqual(selected, ('CUSTOM=1', 'LSF_C_STREAM_NETWORK=1', 'abort=__lsf_c_abort'))
        self.assertEqual(facilities.compiler_defines(facilities.STREAM_STDIO_PROFILE, ('CUSTOM=1',)),
                         (*selected, 'LSF_C_STREAM_STDIO=1'))
        for symbol in (*facilities.STREAM_SYMBOLS, 'LSF_C_STREAM_NETWORK', 'MSG_NOSIGNAL', 'POLLPRI',
                       '__lsf_c_net_send', 'LSF_C_STREAM_STDIO', 'net_stdio_write',
                       '__lsf_c_stdio_initialize',
                       *('__imported_wasi_snapshot_preview1_' + name for name in
                         ('fd_write', 'fd_fdstat_get', 'fd_seek', 'fd_close')),
                       'LSF_C_STANDARD_STREAMS_H', 'abort', '__lsf_c_abort'):
            for profile in facilities.STREAM_PROFILES:
                with self.subTest(symbol=symbol, profile=profile), self.assertRaisesRegex(ValueError, 'compiler-owned-symbol'):
                    facilities.compiler_defines(profile, (symbol + '=1',))
        compiler = Compiler.__new__(Compiler)
        with tempfile.TemporaryDirectory() as temporary, patch('tools.c_guest.compiler.generate') as generate:
            output = Path(temporary) / 'no-output'
            with self.assertRaisesRegex(ValueError, 'requires-cooperative-threading'):
                compiler.compile([Path('missing.c')], Path('missing-wit'), 'service', output,
                                 runtime_profile=facilities.STREAM_PROFILE)
            with self.assertRaisesRegex(ValueError, 'requires-cooperative-threading'):
                compiler.compile([Path('missing.c')], Path('missing-wit'), 'service', output,
                                 runtime_profile=facilities.STREAM_STDIO_PROFILE)
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
            self.assertNotIn('latent:log', result)
            combined = standard_facilities.stage(source, 'service', root / 'combined', ROOT / 'wit/platform',
                                                profile=standard_facilities.STREAM_STDIO_PROFILE)
            combined_text = (combined / 'world.wit').read_text()
            for name in standard_facilities.PROFILE_IMPORTS[standard_facilities.STREAM_STDIO_PROFILE]:
                self.assertEqual(combined_text.count('import ' + name + ';'), 1)
            self.assertEqual(combined_text.count('latent:log/log@0.1.0'), 1)
            self.assertNotIn('wasi:', combined_text)


if __name__ == '__main__':
    unittest.main()

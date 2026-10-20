"""Closed libc preimage and normal compiler capture controls; no C execution claim."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule_project as project
from tools.c_guest import closed_filesystem as port
from tools.c_guest.compiler import Compiler


class ClosedFilesystem(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.sdk = self.root/'sdk'; (self.sdk/'include').mkdir(parents=True)
        self.overlay = project.ROOT/'sdk/c-guest/include/stdio.h'
        (self.sdk/'include/stdio.h').write_bytes(self.overlay.read_bytes())
        self.zig = self.root/'zig'; self.zig.write_bytes(b'fixture-tool')
        self.sources = {}
        for number, name in enumerate(port.SOURCES):
            raw = ('controlled native source '+str(number)+'\n').encode()
            target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            self.sources[name] = (hashlib.sha256(raw).hexdigest(), len(raw))

    def selected(self):
        return patch.dict(port.SOURCES, self.sources, clear=True)

    def test_exact_published_zig_source_selection_is_closed_and_versioned(self):
        self.assertEqual(port.PROFILE, 'c-closed-filesystem-stdio-v1')
        self.assertEqual(port.UPSTREAM, 'https://codeberg.org/ziglang/zig/src/tag/0.16.0/')
        self.assertEqual(port.SOURCES, {
            'lib/libc/include/wasm-wasi-musl/stdio.h':
                ('a7ce495ed82dc11ffb811bcdeec75b4abe743ee88dda78eee4cebfa78ab28244', 7034),
            'lib/libc/wasi/libc-top-half/musl/src/stdio/fopen.c':
                ('961aa0b0b3cf645d7170eafaa072fad00a5f8784bd68ae1db4b0c85f2aa15713', 1159),
        })

    def test_three_materials_preserve_original_bytes_and_detect_late_mutation(self):
        with self.selected():
            before = {name: (self.root/name).read_bytes() for name in self.sources}
            boundary = port.prepare(self.zig, self.sdk)
            self.assertEqual(set(boundary.materials), {
                'c-closed-filesystem-libc-0', 'c-closed-filesystem-libc-1', port.PROFILE})
            boundary.check_unchanged()
            self.assertEqual({name: (self.root/name).read_bytes() for name in self.sources}, before)
            changed = self.root/next(iter(self.sources))
            changed.write_bytes(changed.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError, 'input-changed'):
                boundary.check_unchanged()

    def test_wrong_libc_or_overlay_cannot_be_admitted(self):
        with self.selected():
            for path, reason in ((self.root/next(iter(self.sources)), 'unreviewed-libc-preimage'),
                                 (self.sdk/'include/stdio.h', 'unreviewed-overlay')):
                original = path.read_bytes()
                try:
                    path.write_bytes(original+b'\n')
                    with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, reason):
                        port.prepare(self.zig, self.sdk)
                finally:
                    path.write_bytes(original)

    def test_overlay_keeps_initial_mode_validation_and_refuses_without_imports(self):
        source = self.overlay.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), port.OVERLAY)
        self.assertIn(b'#include_next <stdio.h>\n', source)
        self.assertIn(b'#if defined(__wasi__)\n', source)
        self.assertIn(b'if (!strchr("rwa", *mode)) {\n        errno = EINVAL;\n        return NULL;', source)
        self.assertEqual(source.count(b'errno = ENOTSUP;\n    return NULL;'), 2)
        self.assertIn(b'#define fopen lsf_closed_fopen', source)
        self.assertIn(b'#define tmpfile lsf_closed_tmpfile', source)
        for forbidden in (b'wasm_import', b'latent_', b'pragma', b'__attribute__', b'__fdopen', b'open('):
            self.assertNotIn(forbidden, source.replace(b'lsf_closed_fopen(', b'closed_entry('))

    def test_normal_compiler_admission_binds_port_and_refuses_changed_native_source(self):
        config = {'sdk': {'zig': '0.16.0'}, 'rust': {'dependencies': {'wit-bindgen': '0.62.0'}},
                  'contracts': {'wasm-tools': '1.254.0'}}
        installed = {name: self.root/name for name in ('zig', 'wit-bindgen', 'wasm-tools')}
        for tool in installed.values(): tool.write_bytes(b'fixture-tool')
        versions = {'zig': '0.16.0', 'wit-bindgen': 'wit-bindgen 0.62.0', 'wasm-tools': 'wasm-tools 1.254.0'}
        with self.selected(), patch.object(Compiler, 'run', lambda _self, name, *_: versions[name]):
            compiler = Compiler(self.root/'build', sdk=self.sdk, config=config, installed=installed)
            self.assertEqual(set(compiler.materials), {*installed, 'c-closed-filesystem-libc-0',
                                                      'c-closed-filesystem-libc-1', port.PROFILE})
            compiler.check_unchanged()
            path = self.root/next(iter(self.sources)); path.write_bytes(b'unreviewed native input')
            with self.assertRaisesRegex(ValueError, 'unreviewed-libc-preimage'):
                Compiler(self.root/'rejected', sdk=self.sdk, config=config, installed=installed)

    def test_standard_project_captures_overlay_without_rewriting_application(self):
        app = project.create(self.root/'app', 'greeting')
        files = project.snapshot(app)
        self.assertEqual(files['vendor/lsf/sdk/c-guest/include/stdio.h'], self.overlay.read_bytes())
        original = files['src/main.c']
        project.validate(files)
        self.assertEqual(project.snapshot(app)['src/main.c'], original)
        files['vendor/lsf/sdk/c-guest/include/stdio.h'] += b'\n'
        with self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
            project.validate(files)

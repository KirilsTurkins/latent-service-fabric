"""Source/contract controls only; no C compiler or guest is executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import c_capsule_project
from tools import c_capsule_build
from tools.c_guest import threading
from tools.rust_capsule_project import snapshot


def graph():
    return {'worlds': [{'exports': {'interface-0': {'interface': {'id': 0}}}}],
            'interfaces': [{'name': 'api', 'package': 0, 'types': {}, 'functions': {
                'greet': {'name': 'greet', 'kind': 'freestanding',
                          'params': [{'name': 'name', 'type': 'string'}], 'result': 0}}}],
            'packages': [{'name': 'examples:ordinary@1.0.0'}],
            'types': [{'kind': {'result': {'ok': 'string', 'err': 'string'}}}]}


class CThreadingProfile(unittest.TestCase):
    def test_selection_requires_one_explicit_closed_string(self):
        self.assertFalse(threading.selected({}))
        self.assertFalse(threading.selected({'threadingProfile': 'single-threaded'}))
        self.assertTrue(threading.selected({'threadingProfile': threading.PROFILE}))
        for bad in (True, None, 1, [], {}, 'cooperative', 'rust-context40-sole-consumer-one-task-start-v1'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'unsupported-c-threading-profile'):
                threading.selected({'threadingProfile': bad})

    def test_default_project_and_sdk_bytes_have_no_threading_additions(self):
        self.assertTrue(set(threading.RECIPE).isdisjoint(c_capsule_build.RECIPE))
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            c_capsule_project.create(directory / 'default', 'greeting')
            c_capsule_project.create(directory / 'explicit-default', 'greeting', threading_profile='single-threaded')
            self.assertEqual(snapshot(directory / 'default'), snapshot(directory / 'explicit-default'))
            files = snapshot(directory / 'default')
            self.assertNotIn('threadingProfile', json.loads(files['capsule-project.json']))
            self.assertFalse(any(path.startswith('vendor/lsf/sdk/c-guest/runtime/') for path in files))

    def test_selected_runtime_is_captured_and_lock_checked_before_compilation(self):
        with tempfile.TemporaryDirectory() as root:
            project = c_capsule_project.create(Path(root) / 'selected', 'greeting', threading_profile=threading.PROFILE)
            files = snapshot(project)
            actual, _, _ = c_capsule_project.validate(files)
            self.assertTrue(threading.selected(actual))
            selected = {name for name in files if name.startswith('vendor/lsf/sdk/c-guest/runtime/')}
            self.assertEqual(selected, {'vendor/lsf/sdk/c-guest/runtime/' + name for name in
                                       ('thread-abi.h', 'thread-abi.json', 'threads.c', 'tls-keys.c', 'template-copy.c')})
            for path in selected:
                changed = dict(files, **{path: files[path] + b'\n'})
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'vendored SDK changed'):
                    c_capsule_project.validate(changed)

    def test_linked_tls_symbols_keep_libc_keys_and_encoded_source_keys_separate(self):
        expected = ('pthread_key_create', 'pthread_key_delete', 'pthread_getspecific',
                    'pthread_setspecific', 'tss_create', 'tss_delete', 'tss_get', 'tss_set')
        self.assertEqual(threading.TLS_SYMBOLS, expected)
        self.assertEqual(threading.linked_defines(('OWNED=7',)),
                         ('OWNED=7', 'LSF_C_LINKED_LIBC=1',
                          *(name + '=__lsf_c_' + name for name in expected)))
        for name in ('LSF_C_LINKED_LIBC', *expected,
                     *('__lsf_c_' + item for item in expected)):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'compiler-owned-tls-symbol'):
                threading.linked_defines((name + '=foreign',))
        self.assertNotIn('errno', expected)
        from tools.c_guest.compiler import Compiler
        import inspect
        selected = inspect.getsource(Compiler.compile)
        self.assertIn('defines = threading.linked_defines(defines)', selected)
        self.assertIn('preprocessor.extend("-D" + define for define in defines)', selected)
        self.assertIn('command.extend("-D" + define for define in defines)', selected)
        self.assertIn('or static_libraries', selected)
        self.assertNotIn('--allow-multiple-definition', selected)

    def test_installed_recipe_ships_optional_helper_and_exact_runtime_without_default_selection(self):
        from tools import dev_tool_distribution
        from tools.c_guest import threading_compatibility
        with tempfile.TemporaryDirectory() as root:
            payload = Path(root) / 'payload'
            dev_tool_distribution.recipe(payload, 'c')
            recipe = payload / 'recipe'
            for name in (*threading.RECIPE, *threading_compatibility.RECIPE, *('sdk/c-guest/runtime/' + name for name in
                         ('thread-abi.h', 'thread-abi.json', 'threads.c', 'tls-keys.c', 'template-copy.c'))):
                self.assertEqual((recipe / name).read_bytes(), (c_capsule_project.ROOT / name).read_bytes())
            with patch.object(c_capsule_project, 'ROOT', recipe):
                c_capsule_project.create(Path(root) / 'ordinary', 'greeting')
                selected = c_capsule_project.create(Path(root) / 'selected', 'greeting', threading_profile=threading.PROFILE)
                files = snapshot(selected)
                project, _, _ = c_capsule_project.validate(files)
                self.assertTrue(threading.selected(project))
            ordinary = snapshot(Path(root) / 'ordinary')
            self.assertNotIn('threadingProfile', json.loads(ordinary['capsule-project.json']))
            self.assertFalse(any(name.startswith('vendor/lsf/sdk/c-guest/runtime/') for name in ordinary))

    def test_public_export_comes_from_actual_identity_and_sync_value_graph(self):
        original = graph()
        self.assertEqual(threading.public_export(original), 'examples:ordinary/api@1.0.0#greet')
        mutations = [
            lambda g: g['worlds'].append(g['worlds'][0]),
            lambda g: g['worlds'][0]['exports'].update(other={'interface': {'id': 0}}),
            lambda g: g['interfaces'][0]['functions']['greet'].update(kind='async-freestanding'),
            lambda g: g['types'][0].update(kind={'resource': {}}),
            lambda g: g['interfaces'][0]['types'].update(opaque=0),
            lambda g: g['packages'][0].update(name='foreign@name@1.0.0'),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(original)
            mutation(changed)
            with self.assertRaisesRegex(ValueError, 'finite-public-contract'):
                threading.public_export(changed)

    def test_owned_import_projection_preserves_original_sync_export_and_refuses_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'source'
            source.mkdir()
            text = 'package examples:ordinary@1.0.0;\nworld service { export run: func(); }\n'
            (source / 'world.wit').write_text(text, encoding='utf-8')
            destination = threading.stage(source, 'examples:ordinary/service@1.0.0', root / 'derived',
                                          c_capsule_project.ROOT / 'wit/platform')
            derived = (destination / 'world.wit').read_text(encoding='utf-8')
            self.assertIn('export run: func();', derived)
            self.assertNotIn('async', derived)
            for imported in threading.IMPORTS:
                self.assertEqual(derived.count('import ' + imported + ';'), 1)
            self.assertEqual((source / 'world.wit').read_text(encoding='utf-8'), text)
            with self.assertRaisesRegex(ValueError, 'must-be-owned-by-profile'):
                threading.stage(destination, 'examples:ordinary/service@1.0.0', root / 'again',
                                c_capsule_project.ROOT / 'wit/platform')

    def test_closed_libc_material_labels_preserve_original_paths_and_recheck_the_same_files(self):
        from types import SimpleNamespace
        from tools.c_guest.compiler import Compiler
        from tools.build_observation import file_identity
        names=sorted(threading.LIBC)
        self.assertEqual([threading.libc_material_name(name) for name in names],
                         ['c-threading-libc-'+str(i) for i in range(10)])
        with self.assertRaisesRegex(ValueError,'original-libc-material-path'):
            threading.libc_material_name('lib/unknown/errno.c')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);paths={}
            for i,name in enumerate(names):
                path=root/('controlled-'+str(i));path.write_bytes(('controlled source '+str(i)).encode())
                paths[name]=path
            zig=root/'zig';zig.write_bytes(b'controlled unchanged tool')
            compiler=Compiler.__new__(Compiler)
            compiler.closed_filesystem=SimpleNamespace(check_unchanged=lambda:None)
            compiler.threading_inputs=paths;compiler.paths={'zig':zig};compiler.isolation=None
            compiler.materials={'zig':file_identity(zig,'zig')}
            compiler.materials.update({name:file_identity(path,threading.libc_material_name(name),32768)
                                      for name,path in paths.items()})
            self.assertEqual(set(compiler.threading_inputs),set(threading.LIBC))
            self.assertTrue(all('/' not in row['name'] for row in compiler.materials.values()))
            with patch.object(threading,'libc_inputs',return_value=paths):
                compiler.check_unchanged()
                original=compiler.materials[names[0]]['name'];compiler.materials[names[0]]['name']=names[0]
                with self.assertRaisesRegex(ValueError,'libc-input-changed'):compiler.check_unchanged()
                compiler.materials[names[0]]['name']=original;paths[names[0]].write_bytes(b'changed source')
                with self.assertRaisesRegex(ValueError,'libc-input-changed'):compiler.check_unchanged()


if __name__ == '__main__':
    unittest.main()

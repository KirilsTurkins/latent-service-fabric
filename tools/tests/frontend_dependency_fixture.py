"""Real capture setup for consumer construction boundaries, without compiler success."""
import json
from pathlib import Path
import shutil
import tempfile

from tools import application_dependencies as dependencies, guest_dependency_inputs as inputs
from tools.build_snapshot import canonical, digest
from tools.dev_workflow import common, project
from tools.tests.test_dev_contracts import descriptor


class FrontendFixture:
    def __init__(self, test, language, creator, *, native_inputs=None):
        temporary = tempfile.TemporaryDirectory(prefix='lsf-frontend-consumer-')
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.owner = self.root / 'project'
        self.owner.mkdir()
        self.app = creator(self.owner / 'app', 'greeting')
        self.output = self.owner / 'output'
        self.language = language
        self.sdk_lock = (self.app / 'sdk-lock.json').read_bytes()
        self.native = b'exact reviewed native input'
        selected_native = {'native.lock': self.native, **(native_inputs or {})}
        for name, raw in selected_native.items():
            (self.app / name).write_bytes(raw)
        self.tools = self.root / 'tools'; self.tools.mkdir()
        self.tool = self.tools / 'boundary-only-tool'
        self.tool.write_bytes(b'never executed; constructor boundary control only')
        value = descriptor()
        value.update(language=language, inputRoots=['app'])
        value['template']['ownerIssue'] = project.LANGUAGES[language]
        value['build']['workingDirectory'] = 'app'
        (self.owner / inputs.DESCRIPTOR).write_bytes(common.encode(value))
        self.library = self.root / 'outside-uncatalogued-library'; self.library.mkdir()
        (self.library / 'library.txt').write_bytes(b'real captured outside library')
        manifest = {'formatVersion': 1, 'language': language,
            'selection': {'profile': 'selected-construction-boundary-v1'},
            'nativeLocks': ['app/' + name for name in selected_native], 'artifacts': [{
                'id': 'outside/unlisted/1.0', 'role': 'application', 'format': 'directory',
                'mount': 'dependencies/selected', 'source': {'path': str(self.library)},
                'dependencies': [], 'metadata': {'license': 'MIT'}}], 'transformations': []}
        (self.owner / dependencies.MANIFEST).write_bytes(canonical(manifest))
        self.lock = dependencies.capture(self.owner)
        (self.owner / dependencies.LOCK).write_bytes(canonical(self.lock))
        shutil.rmtree(self.library)

    def assert_observed(self, test):
        observed = json.loads((self.output / 'source-inputs.json').read_bytes())
        for name in (inputs.DESCRIPTOR, inputs.MAPPING, dependencies.MANIFEST, dependencies.LOCK):
            test.assertIn(name, observed)
        test.assertEqual(observed['native.lock'], {'digest': digest(self.native), 'size': len(self.native)})
        test.assertEqual(observed['sdk-lock.json'], {'digest': digest(self.sdk_lock), 'size': len(self.sdk_lock)})
        test.assertEqual((self.app / 'sdk-lock.json').read_bytes(), self.sdk_lock)
        recipe = json.loads((self.output / 'recipe-inputs.json').read_bytes())
        for name in inputs.RECIPE:
            test.assertIn(name, recipe)
        test.assertFalse(any(name.startswith('dependency-inputs/') for name in observed))
        test.assertFalse((self.output / 'BUILD-COMPLETE.json').exists())

    def prepare_boundary(self, test, called):
        def stop(owner, work, output, language, **kwargs):
            closure = dependencies.prepare(owner, work, output, language, **kwargs)
            called.append(owner)
            test.assertEqual(owner, self.owner)
            test.assertIsNotNone(closure)
            test.assertEqual(inputs.read_native(closure, 'native.lock'), self.native)
            test.assertEqual((work / 'dependencies/selected/library.txt').read_bytes(), b'real captured outside library')
            raise ValueError('intentional-before-language-compiler-boundary')
        return stop

    def tamper(self):
        row = self.lock['artifacts'][0]['files'][0]
        from tools.application_dependency_store import Store
        Store(self.owner / 'dependency-inputs/objects', create=False).path(row['digest']).write_bytes(b'tampered')

    def shadow(self):
        (self.app / dependencies.MANIFEST).write_bytes((self.owner / dependencies.MANIFEST).read_bytes())

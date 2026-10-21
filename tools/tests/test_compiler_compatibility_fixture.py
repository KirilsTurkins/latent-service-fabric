"""Fixture/source controls only; no TeaVM, ILC or signed execution credit."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import io

from tools import compiler_compatibility_fixture as fixture
from tools.java_guest.reachability import class_methods
from tools.rust_capsule_project import ROOT, read_file
from tools.phase2_operator_process import WorkflowError


class CompatibilityFixtures(unittest.TestCase):
    def test_projects_keep_unchanged_normal_limits_and_exact_vendored_sdk(self):
        import json
        from tools.rust_capsule_project import snapshot, inventory
        for language in ('java', 'dotnet'):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as name:
                app = fixture.project(language, Path(name)/'app')
                descriptor = json.loads(read_file(app/'capsule-project.json'))
                lock = json.loads(read_file(app/'sdk-lock.json'))
                self.assertEqual(descriptor['limits']['cpuFuel'], 1_000_000_000)
                self.assertEqual(descriptor['limits']['wallTimeLimitMillis'], 120000)
                self.assertEqual(descriptor['limits']['logBytes'], 0)
                self.assertEqual(lock['sdk'], json.loads(inventory(snapshot(app/'vendor/lsf'))))
                self.assertIn(b'greet: async func(', read_file(app/'wit/world.wit'))
                import re
                declarations = re.findall(rb'import ([A-Za-z0-9:/@.\-]+);', read_file(app/'wit/world.wit'))
                self.assertEqual(set(value.decode() for value in declarations), set(fixture.DECLARATIONS[language]))
                if language == 'dotnet':
                    from tools.dotnet_guest import managed_work, runtime
                    self.assertTrue(managed_work.selected(list(fixture.DECLARATIONS[language])))
                    self.assertEqual(runtime.select(list(fixture.DECLARATIONS[language]), [], managed_work=True), 'runtime-managed')
                self.assertEqual(read_file(app/'wit/deps/activation-runtime/package.wit'),
                    read_file(ROOT/'wit/platform/activation-runtime/package.wit'))

    def test_counterfactual_changes_only_one_root_edge_and_keeps_reviewed_dependencies(self):
        original = read_file(ROOT/(fixture.SOURCE+'java')/'Capsule.java')
        with tempfile.TemporaryDirectory() as name:
            app = Path(name); target = app/'src/dev/latent/app/Capsule.java'
            target.parent.mkdir(parents=True); target.write_bytes(original)
            closure = SimpleNamespace(identity='model-captured-input-identity')
            with patch.object(fixture.inputs, 'verify_inputs', return_value=closure) as verify:
                record = fixture.counterfactual_java(app)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(target.read_bytes().replace(fixture.JAVA_REACHED, fixture.JAVA_EDGE), original)
            self.assertIs(record['compilerFailureObserved'], False)
            self.assertIs(record['libraryBytesChanged'], False)
            with patch.object(fixture.inputs, 'verify_inputs', return_value=closure), self.assertRaises(WorkflowError):
                fixture.counterfactual_java(app)
            target.write_bytes(original)
            with patch.object(fixture.inputs, 'verify_inputs', side_effect=[closure, SimpleNamespace(identity='changed')]), \
                    self.assertRaisesRegex(WorkflowError, 'library-identity'):
                fixture.counterfactual_java(app)

    def test_actual_javac_preserves_transitive_native_init_constructor_and_callback_definitions(self):
        javac = shutil.which('javac')
        if javac is None: self.skipTest('JDK required for actual passive metadata source control')
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); classes = root/'classes'
            sources = [ROOT/(fixture.SOURCE+'java')/part for part in ('Core.java', 'Library.java')]
            before = {str(path): path.read_bytes() for path in sources}
            subprocess.run([javac, '-proc:none', '-encoding', 'UTF-8', '-d', str(classes),
                *(str(path) for path in sources)], check=True, capture_output=True, timeout=30)
            metadata = {owner: methods for path in classes.rglob('*.class')
                for owner, methods in [class_methods(path.read_bytes())]}
            core = {row['method']: row for row in metadata['outside.diagnosticsdata.Core']}
            self.assertTrue(core['opaqueNative()I']['nativeWithoutAnnotations'])
            self.assertEqual(core['<clinit>()V']['kind'], 'initialization')
            self.assertEqual(core['<init>()V']['kind'], 'constructor')
            self.assertIn('run()V', {row['method'] for row in metadata['outside.diagnostics.Library$1']})
            self.assertEqual({str(path): path.read_bytes() for path in sources}, before)

    def test_dotnet_outside_projects_have_only_two_fixed_sources_and_one_transitive_edge(self):
        import xml.etree.ElementTree as xml
        with tempfile.TemporaryDirectory() as name:
            root = fixture.dotnet_sources(Path(name)/'library')
            for path, source in ((root/'Library.csproj', 'Library.cs'), (root/'child/Data.csproj', 'Core.cs')):
                node = xml.fromstring(path.read_bytes())
                self.assertEqual(node.attrib, {'Sdk': 'Microsoft.NET.Sdk'})
                self.assertEqual([value.attrib for value in node.iter('Compile')], [{'Include': source}])
                for tag in ('PackageReference', 'Import', 'Reference', 'Exec', 'Target'):
                    self.assertEqual(list(node.iter(tag)), [])
            self.assertEqual([value.attrib for value in xml.fromstring((root/'Library.csproj').read_bytes()).iter('ProjectReference')],
                [{'Include': 'child/Data.csproj'}])
            self.assertEqual((root/'Library.cs').read_bytes(), read_file(ROOT/(fixture.SOURCE+'dotnet')/'Library.cs'))
            self.assertEqual((root/'child/Core.cs').read_bytes(), read_file(ROOT/(fixture.SOURCE+'dotnet')/'Core.cs'))
            raw = fixture.dotnet_package(fixture.DOTNET_IDS[0], b'model-CIL-not-guest-code')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(set(archive.namelist()), {fixture.DOTNET_IDS[0]+'.nuspec',
                    'lib/net10.0/'+fixture.DOTNET_IDS[0]+'.dll'})
                self.assertIn(fixture.DOTNET_IDS[1].encode(), archive.read(fixture.DOTNET_IDS[0]+'.nuspec'))

    def test_ordinary_callback_sources_preserve_real_join_and_separate_uncaught_paths(self):
        java = read_file(ROOT/(fixture.SOURCE+'java')/'Library.java').decode()
        dotnet = read_file(ROOT/(fixture.SOURCE+'dotnet')/'Library.cs').decode()
        self.assertIn('timer.schedule(new TimerTask()', java)
        self.assertIn('while (!state.finished)', java)
        self.assertIn('finally { timer.cancel(); }', java)
        self.assertIn('Task.Run(Callback).GetAwaiter().GetResult()', dotnet)
        self.assertIn('Task.Run(FailingCallback).GetAwaiter().GetResult()', dotnet)
        for source in (java, dotnet):
            self.assertIn('init-trap', source); self.assertIn('callback-trap', source)
            self.assertNotIn('setDefault', source)
        for language in ('java', 'dotnet'):
            source = read_file(ROOT/(fixture.SOURCE+language)/('Core.java' if language=='java' else 'Core.cs')).decode()
            self.assertIn('diagnostics-never-contact', source)
            self.assertIn('6 * 7', source)


if __name__ == '__main__': unittest.main()

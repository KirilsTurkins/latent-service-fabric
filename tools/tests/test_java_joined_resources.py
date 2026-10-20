"""Normal Java source and nested class inputs for joined resource callbacks."""
from pathlib import Path
import tempfile
import unittest

from tools import java_resource_runtime_fixture as fixture
from tools.java_capsule_project import create, validate
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT,read_file,read_json,snapshot


class JavaJoinedResources(unittest.TestCase):
    def test_project_uses_current_sdk_and_explicit_facilities_without_altering_original_budgets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);ordinary=create(root/'ordinary','greeting');app=fixture.project(root/'joined')
            old,new=(read_json(path/'capsule-project.json') for path in (ordinary,app))
            old['limits']['logBytes']=256
            self.assertEqual(old,new)
            self.assertEqual(read_json(ordinary/'sdk-lock.json')['sdk'],read_json(app/'sdk-lock.json')['sdk'])
            self.assertEqual(read_file(app/'src/dev/latent/app/Capsule.java'),read_file(ROOT/fixture.MATERIALS[0]))
            self.assertEqual(len(list((app/'src').rglob('*.java'))),1)
            wit=read_file(app/'wit/world.wit')
            for capability in fixture.CAPABILITIES:self.assertEqual(wit.count(('import '+capability+';').encode()),2 if 'clock/' in capability else 1)
            validate(snapshot(app))

    @staticmethod
    def classes(root):
        files={name+'.class':b'controlled compiled class' for name in fixture.CLASSES}
        files[fixture.CLASSES[0]+'$Shared.class']=b'controlled member class'
        files[fixture.CLASSES[0]+'$1.class']=b'controlled ordinary TimerTask class'
        for name,raw in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        return files

    def test_ordinary_member_and_anonymous_classes_are_preserved_without_source_path_filtering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);expected=self.classes(root)
            self.assertEqual(fixture.compiled_classes(root),expected)
            with self.assertRaisesRegex(ValueError,'nonportable project path'):snapshot(root)

    def test_foreign_prefixed_class_and_missing_required_class_are_refused(self):
        for change in ('foreign-prefix','foreign-directory','missing'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);self.classes(root)
                if change=='missing':(root/(fixture.CLASSES[1]+'.class')).unlink()
                else:
                    name=fixture.CLASSES[0]+'Other.class' if change=='foreign-prefix' else 'outside/foreign/Other.class'
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'foreign class')
                with self.assertRaises(WorkflowError):fixture.compiled_classes(root)

    def test_generated_class_set_is_bounded_before_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.classes(root)
            for index in range(65):(root/(fixture.CLASSES[0]+'$C'+str(index)+'.class')).write_bytes(b'controlled')
            with self.assertRaisesRegex(WorkflowError,'class-bound-or-link'):fixture.compiled_classes(root)

    def test_compiler_mutation_of_original_library_is_refused_before_jar_authoring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            class Commands:
                def run(self,*_args):
                    (root/'outside-originals/sources/parent/Library.java').write_bytes(b'changed compiler input')
            with self.assertRaisesRegex(WorkflowError,'original-library-source-changed'):
                fixture.capture(root,Commands())

"""Fixed public compiler diagnostic; this is not guest qualification."""
import hashlib
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class ClassInfoDiagnostic(unittest.TestCase):
    def test_numeric_marker_has_fixed_public_buckets_and_does_not_change_the_guard(self):
        source = (ROOT/'tools/java_guest/coroutine_patch.py').read_text(encoding='utf-8')
        start = source.index('    private IllegalStateException progressNativeRefusal(')
        end = source.index('    private void validateNonsuspendableProgress()', start)
        body = source[start:end]
        self.assertEqual(body.count('if (group == 16)'), 2)
        self.assertIn('latent.java.progress-class-info.v1 " + metadata', body)
        self.assertIn('return progressRefusal(2, owner);', body)
        self.assertNotIn('println(method.getName()', body)
        self.assertNotIn('println(owner.getName()', body)
        self.assertNotIn('println(method.getDescriptor()', body)
        self.assertIn('"arrayType", "declaringClass", "enclosingClass"', body)
        self.assertIn('"enumConstantCount", "enumConstant"', body)
        # The complete diagnostic inverse restores the original source exactly.
        updated = 'int group = 0, flags = 0, metadata = 0;'
        self.assertEqual(source.count(updated), 1)
        original = source.replace(updated, 'int group = 0, flags = 0;', 1)
        begin = original.index('            // Only fixed public TeaVM ClassInfo declaration names are bucketed.')
        finish = original.index('            if (method.hasModifier(ElementModifier.NATIVE)) flags |= 1;', begin)
        original = original[:begin] + original[finish:]
        begin = original.index('        if (group == 16) {\n            System.err.println("latent.java.progress-class-info.v1 "')
        finish = original.index('        return progressRefusal(2, owner);', begin)
        diagnostic = original[begin:finish]
        self.assertIn('if (metadata == 13)', diagnostic)
        self.assertIn('latent.java.progress-class-info-check.v1 " + stage', diagnostic)
        for stage in range(1, 8):
            self.assertIn('stage = %s;' % stage, diagnostic)
        original = original[:begin] + original[finish:]
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         '48a709f95feda2175cece9f54c0f0b50ce5ad53964142286a121dbdb329f2f91')

    def test_workflow_uses_only_fixed_branch_public_fixture_and_retained_compiler_logs(self):
        workflow = yaml.safe_load((ROOT/'.github/workflows/java-classinfo-fiber-diagnostic.yml').read_text())
        trigger = workflow.get('on', workflow.get(True))
        self.assertEqual(trigger, {'push': {'branches': ['diag/java-classinfo-fibers-20261104']}})
        self.assertFalse(workflow['concurrency']['cancel-in-progress'])
        self.assertEqual(set(workflow['jobs']), {'fiber-compiler'})
        job = workflow['jobs']['fiber-compiler']
        commands = [step['run'] for step in job['steps'] if 'run' in step]
        self.assertEqual(sum('tools/qualify_java_fibers.py' in command for command in commands), 1)
        self.assertNotIn('--fixture', commands[-1])
        self.assertIn('--wasi-sdk "$LSF_JAVA_CLASSINFO_WASI_SDK"', commands[-1])
        self.assertTrue(any('compiler_profile_distribution.py stage' in command for command in commands))
        self.assertFalse(any('cargo ' in command or '|| true' in command for command in commands))
        upload = job['steps'][-1]
        self.assertEqual(upload['if'], 'always()')
        self.assertIn('compiler/*-java-to-c.log', upload['with']['path'])
        self.assertNotIn('key', upload['with']['path'].lower())

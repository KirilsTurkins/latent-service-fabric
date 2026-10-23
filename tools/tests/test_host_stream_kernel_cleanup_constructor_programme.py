"""Finite changed-TU membership and conservative geometry controls; no build."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_cleanup_constructor_programme as source
from tools import qualify_host_stream_kernel_cleanup_constructor as recipe


class CleanupConstructorProgrammeSource(unittest.TestCase):
    def test_only_four_changed_defining_objects_and_no_old_programme_replay(self):
        self.assertEqual(set(source.TARGETS),{'net/factory.o','kernel/kthread.o',
            'kernel/workqueue.o','drivers/acpi/osl.o'})
        self.assertEqual(set(source.TARGETS),set(recipe.REQUIRED))
        self.assertEqual(set(source.GEOMETRY),set(source.TARGETS))
        text=Path(recipe.__file__).read_text()
        self.assertNotIn('atomic.program()',text)
        self.assertNotIn('24-affected-real-kbuild-objects',text)
        self.assertIn("origin['GITHUB_EVENT_NAME'] in ('workflow_dispatch','push')",text)
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):
            recipe.run(Path('no-archive'),Path('no-output'))

    def test_paid_completion_expiry_and_provider_waitqueue_are_real_sizeof(self):
        wq=dict(source.GEOMETRY['kernel/workqueue.o'][1])
        acpi=dict(source.GEOMETRY['drivers/acpi/osl.o'][1])
        self.assertEqual(wq['birthCompletionBytes'],
            'sizeof(((struct lsf_cleanup_provider_control *)NULL)->born)')
        self.assertEqual(wq['constructorExpiryBytes'],
            'sizeof(((struct lsf_cleanup_provider_control *)NULL)->constructor_expires)')
        self.assertEqual(acpi['constructorWaitqueueBytes'],'sizeof(lsf_acpi_provider_constructor_wait)')
        for target,(symbol,fields) in source.GEOMETRY.items():
            self.assertEqual(len(fields),len({name for name,_ in fields}))
            self.assertIn(symbol.encode(),source.geometry_suffix(target))

    def test_new_fixed_record_fit_never_certifies_whole_bootstrap_or_runtime(self):
        # Synthetic values exercise refusal arithmetic, not observed geometry.
        values={target:{key:1 for key,_ in fields} for target,(_,fields) in source.GEOMETRY.items()}
        values['net/factory.o'].update(backingBytes=524288,infrastructureBytes=196608,
            bootstrapCeiling=1048576,allocationSlots=256)
        values['kernel/workqueue.o'].update(cpuMaximum=64,constructorExpiryBytes=8,pwqAlignment=256)
        result=source.fitting(values)
        self.assertEqual(result['providerRecordBytes']['pwq'],256)
        for key in ('completeBootstrapRemeasured','wholeInfrastructureFitQualified',
            'initialBirthBounded','publicIoCallIntegrated','actualLinuxExecution',
            'consumerSelected','completeAllocationClosure','productionInstallation'):
            self.assertFalse(result[key])
        for field,value in (('poolBytes',196608),('pwqAlignment',8192),('constructorExpiryBytes',4)):
            old=values['kernel/workqueue.o'][field]
            values['kernel/workqueue.o'][field]=value
            with self.assertRaises(ValueError):
                source.fitting(values)
            values['kernel/workqueue.o'][field]=old


if __name__=='__main__':
    unittest.main()

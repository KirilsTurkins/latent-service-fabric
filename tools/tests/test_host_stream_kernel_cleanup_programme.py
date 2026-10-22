"""Finite programme membership/geometry/error controls, no Kbuild invocation."""
import unittest
from tools import host_stream_kernel_cleanup_programme as source
from tools import host_stream_kernel_cleanup_atomic_control as atomic
from tools import qualify_host_stream_kernel_cleanup_lifecycle as recipe


class CleanupProgrammeSource(unittest.TestCase):
    def test_original_recipe_unchanged_and_fixed_new_programme(self):
        self.assertEqual(len(source.STAGES), 24)
        selected = set(recipe.EXTRA_OBJECTS) | set(source.baseline.object_selection())
        self.assertEqual(len(selected),24)
        self.assertTrue(set(source.GEOMETRY) <= selected)
        self.assertEqual(len(recipe.recipe_inputs()),5)
        self.assertIn('selected.config',source.source_names())
        self.assertFalse(any(path.startswith('/') or '..' in path.split('/') for path in source.source_names()))

    def test_geometry_stays_in_real_defining_translation_units(self):
        for target, (symbol, fields) in source.GEOMETRY.items():
            suffix = source.geometry_suffix(target)
            self.assertIn(symbol.encode(),suffix)
            self.assertIn(source.baseline.GEOMETRY_SECTION.encode(),suffix)
            self.assertEqual(len(fields),len(set(key for key,_ in fields)))
        wq = dict(source.GEOMETRY['kernel/workqueue.o'][1])
        self.assertEqual(wq['pwqBytes'],'sizeof(struct pool_workqueue)')
        self.assertEqual(wq['pwqAlignment'],'__alignof__(struct pool_workqueue)')
        self.assertIn('NR_CPUS',wq['contextMaximumBytes'])
        self.assertNotIn('blob_sizes.lbs_task',dict(source.GEOMETRY['kernel/fork.o'][1]).values())

    def test_exact_atomic_leaf_and_failure_programmes_are_real_generated_c(self):
        text = atomic.program().decode()
        self.assertEqual(text.count(atomic.source.atomic_nonfinal()),1)
        self.assertIn('__atomic_compare_exchange_n(refs, expected, desired, 0,',text)
        self.assertIn('__ATOMIC_RELEASE, __ATOMIC_RELAXED',text)
        for token in ('check(1u, 0, -EOPNOTSUPP, 1u, 0)',
                      'check(2u, -1, -EOPNOTSUPP, 1u, 1)',
                      'check(3u, -1, 0, 1u, 2)',
                      'check(REFCOUNT_SATURATED, 0, -EOVERFLOW, REFCOUNT_SATURATED, 0)',
                      'check(0xffffffffu, 0, -EIO, 0xffffffffu, 0)',
                      'check(0x80000000u, 0, -EIO, 0x80000000u, 0)',
                      'check(0u, 0, -EIO, 0u, 0)', 'destructor_calls != 1'):
            self.assertIn(token,text)
        for token in ('lsf_device_finish(', 'kobject_put(', 'acpi_dev_put(', 'malloc(', 'free('):
            self.assertNotIn(token,text)

    @staticmethod
    def sample_values():
        # Deliberately synthetic geometry verifies bound/error arithmetic only.
        values = {target:{key:1 for key,_ in fields} for target,(_,fields) in source.GEOMETRY.items()}
        values['net/factory.o'].update(backingBytes=524288,infrastructureBytes=196608,
            bootstrapCeiling=1048576,allocationSlots=256,factoryFixedBytes=40000)
        values['kernel/workqueue.o']['cpuMaximum']=64
        values['kernel/workqueue.o']['pwqAlignment']=256
        return values

    def test_same_record_alignment_and_runtime_unknowns_do_not_become_fit_claims(self):
        values=self.sample_values()
        result=source.fitting(values)
        self.assertEqual(result['providerRecordBytes']['pwq'],256)
        self.assertEqual(result['providerRecords'],6)
        for key in ('wholeInfrastructureFitQualified','runtimeArchTaskBytesKnown',
                    'runtimeLsmCompositeBytesKnown','actualRuntimeGeometryExecuted',
                    'consumerSelected','actualNativeLedger','productionInstallation'):
            self.assertFalse(result[key])

    def test_capacity_bootstrap_and_geometry_fail_closed(self):
        for field,value in (('poolBytes',196608),('pwqAlignment',8192),('cpuMaximum',65)):
            values=self.sample_values()
            values['kernel/workqueue.o'][field]=value
            with self.assertRaises(ValueError):
                source.fitting(values)
        values=self.sample_values()
        values['net/factory.o']['factoryFixedBytes']=1048576
        with self.assertRaises(ValueError):
            source.fitting(values)


if __name__ == '__main__':
    unittest.main()

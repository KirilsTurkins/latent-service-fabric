"""Strict fresh serial evidence and actual original-runner budget controls."""
import hashlib
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import host_stream_kernel_no_begin_vm as source
from tools import host_stream_kernel_late_fd_vm as late
from tools import host_stream_kernel_vm_image as image
from tools import qualify_host_stream_kernel_objects as objects
from tools.host_stream_kernel_cleanup_native import OWNED, function

BOOT = b'LSFVM1 boot=constructor-only production-sockets=disabled'
OPENED = (b'LSFVM1 snapshot=opened state=0 error=0'
    b' field0=0 field1=0 field2=0 field3=0 field4=0 field5=0 field6=2 field7=0 field8=0 field9=0')
LEAVES = {
    'static int log_number(':'015624137e470c5c75dd0f200b6fe6f29b5822caaa86f058f22fbba3099ef73b',
    'static int log_marker(':'c63271ae62977a81bc7e579c0d5daf081f264be6450d7d88c780f6ed78c5ded1',
    'static int observe_log_record(':'61c11e79fc66981225a3a72e88c33ad3c8eaee432492ef23e6623b05f62c0ef1',
    'static int kmsg_controls(':'b1dd492a00ed249ec17c7815e8643a7a4bb696227e7c2a936f840c237475e997',
    'static void wait_outside_collector(':'5865fd55ef9efcdc588ffdf6df869e148903a9b516e0e58b551af7d0c3e88253',
}


def serial(*, prefix=b'[    2.401492] ', after=False):
    rows = [BOOT, OPENED, source.NO_BEGIN_CHECK]
    rows.insert(3 if after else 2, prefix+image.PHYSICAL_MARKER)
    return b'\n'.join(rows)+b'\n'


def commands(directory):
    root = Path(directory)
    output = root/'commands'
    output.mkdir()
    return objects.Commands(root, output, {}, deadline_seconds=2400, command_seconds=1800)


def successful_process():
    return SimpleNamespace(output=b'original output',stderr=b'',returncode=0,elapsed_ms=1,cleaned=True)


class NoBeginVm(unittest.TestCase):
    def test_compile_selector_exits_after_opened_snapshot_before_any_begin_and_preserves_old_c_controls(self):
        raw = (OWNED/'constructor-vm-init.c').read_bytes()
        self.assertEqual(source.no_begin_probe_source(raw), source.SELECTOR+raw)
        for bad in (source.SELECTOR+raw, late.SELECTOR+raw, b'foreign source', b'x'*65536):
            with self.subTest(bad=bad[:30]), self.assertRaises(ValueError):
                source.no_begin_probe_source(bad)
        text = raw.decode()
        main = function(text, 'int main(')
        branch = re.search(r'#if LSF_VM_NO_BEGIN\n(.*?)#endif', main, re.S)[1]
        self.assertLess(main.index('snapshot("opened", before)'), main.index('#if LSF_VM_NO_BEGIN'))
        self.assertLess(main.index('#if LSF_VM_NO_BEGIN'), main.index('request(bytes, BEGIN'))
        self.assertIn('check(close(fd) == 0, "no-begin-descriptor-close")', branch)
        self.assertIn('finish(1, "actual-no-begin-descriptor-close-returned")', branch)
        self.assertIn('return 1;', branch)
        for forbidden in ('request(', 'write(', 'snapshot(', 'fork(', '/dev/kmsg', image.PHYSICAL_MARKER.decode()):
            self.assertNotIn(forbidden, branch)
        self.assertIn('(LSF_VM_NO_BEGIN && LSF_VM_LATE_FD)', text)
        self.assertNotIn(image.PHYSICAL_MARKER, raw)
        for prefix, digest in LEAVES.items():
            self.assertEqual(hashlib.sha256(function(text,prefix).encode()).hexdigest(), digest)
        self.assertIn('cases != 22', text)
        self.assertLess(main.index('return kmsg_controls()'), main.index('getpid() != 1'))

    def test_unique_real_marker_with_independent_pid1_order_preserves_raw_identity(self):
        for prefix in (b'', b'[    2.401492] '):
            for after in (False, True):
                raw = serial(prefix=prefix, after=after)
                value = source.serial_observation(raw)
                self.assertTrue(value['rootFinalFree'])
                self.assertTrue(value['noBeginCollection'])
                self.assertFalse(value['childConstructorStarted'])
                self.assertEqual(value['snapshots'], {'opened':dict(state=0,error=0,
                    fields=[0,0,0,0,0,0,2,0,0,0])})
                self.assertEqual(value['bytes'],len(raw))
                self.assertEqual(value['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(value['physicalReturn']['kernelObservations'],1)
                self.assertTrue(value['physicalReturn']['independentPid1UartOrder'])
                self.assertFalse(value['physicalReturn']['nativeQuotaRelease'])

    def test_missing_duplicate_wrong_history_faults_and_unknown_rows_refuse(self):
        raw = serial()
        bad = [b'', b'x'*(image.MAX_SERIAL+1), raw.replace(image.PHYSICAL_MARKER,b'absent'),
            raw+image.PHYSICAL_MARKER+b'\n', raw+b'Kernel panic', raw+b'BUG:', raw+b'Oops:',
            raw+late.HANDOFF+b'\n', raw+late.OUTSIDE+b'\n',
            raw+OPENED.replace(b'snapshot=opened',b'snapshot=ready')+b'\n',
            raw+OPENED.replace(b'snapshot=opened',b'snapshot=child-retired-root-held')+b'\n',
            raw.replace(b'state=0',b'state=2'), raw.replace(b'error=0',b'error=1'),
            raw.replace(source.NO_BEGIN_CHECK,image.ROOT_RELEASE_CHECK),
            raw.replace(b'[    2.401492]',b'[    2.40149]'),
            raw.replace(b'[    2.401492]',b'[           2.401492]'),
            raw+b'[ 2.401492] LSFVM1 invented=observation\n',
            b'\n'.join([OPENED,BOOT,image.PHYSICAL_MARKER,source.NO_BEGIN_CHECK])+b'\n']
        for index in range(10):
            actual = 2 if index == 6 else 0
            bad.append(raw.replace(f'field{index}={actual}'.encode(),f'field{index}={actual+1}'.encode()))
        for item in bad:
            with self.subTest(raw=item[:160]), self.assertRaises(ValueError):
                source.serial_observation(item)

    def test_actual_three_command_timeouts_use_shared_remaining_deadline_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = commands(directory)
            prior = runner.command_seconds, runner.deadline
            with patch.object(source.time,'monotonic',side_effect=[1000,1000,1090,1179,1179.5]), \
                    patch.object(objects,'run_owned',return_value=successful_process()) as process:
                with source.shared_vm_budget(runner) as budget:
                    for stage in ('first','second','third'):
                        runner.run(stage,'observed-command')
                self.assertEqual([call.kwargs['timeout'] for call in process.call_args_list],[90,90,1])
            self.assertEqual((runner.command_seconds,runner.deadline),prior)
            self.assertEqual(budget['aggregateMaximumSeconds'],180)
            self.assertTrue(budget['perCommandMaximaAreNotAdditive'])
            self.assertEqual(budget['elapsedMillis'],179500)
            self.assertEqual(len(runner.records),3)

    def test_actual_expiry_before_third_prevents_process_start_and_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = commands(directory)
            prior = runner.command_seconds, runner.deadline
            with patch.object(source.time,'monotonic',side_effect=[1000,1000,1090,1180]), \
                    patch.object(objects,'run_owned',return_value=successful_process()) as process:
                with self.assertRaisesRegex(ValueError,'original-command-deadline'):
                    with source.shared_vm_budget(runner):
                        for stage in ('first','second','third'):
                            runner.run(stage,'observed-command')
                self.assertEqual(process.call_count,2)
            self.assertEqual((runner.command_seconds,runner.deadline),prior)

    def test_last_successful_return_cannot_pass_after_aggregate_deadline_or_mask_prior_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = commands(directory)
            prior = runner.command_seconds, runner.deadline
            with patch.object(source.time,'monotonic',side_effect=[1000,1000,1090,1179,1181]), \
                    patch.object(objects,'run_owned',return_value=successful_process()) as process:
                with self.assertRaisesRegex(ValueError,'aggregate-vm-deadline'):
                    with source.shared_vm_budget(runner):
                        for stage in ('first','second','third'):
                            runner.run(stage,'observed-command')
                self.assertEqual(process.call_count,3)
            self.assertEqual((runner.command_seconds,runner.deadline),prior)
            with patch.object(source.time,'monotonic',side_effect=[1000,1000]), \
                    patch.object(objects,'run_owned',side_effect=RuntimeError('original-owner-failure')):
                with self.assertRaisesRegex(RuntimeError,'original-owner-failure'):
                    with source.shared_vm_budget(runner):
                        runner.run('failing','observed-command')
            self.assertEqual((runner.command_seconds,runner.deadline),prior)

    def test_original_shorter_command_and_aggregate_limits_are_never_increased(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = commands(directory)
            runner.command_seconds, runner.deadline = 45, 1060
            with patch.object(source.time,'monotonic',side_effect=[1000,1000,1059,1060]), \
                    patch.object(objects,'run_owned',return_value=successful_process()) as process:
                with source.shared_vm_budget(runner):
                    runner.run('first','observed-command')
                    runner.run('second','observed-command')
                self.assertEqual([call.kwargs['timeout'] for call in process.call_args_list],[45,1])
            self.assertEqual((runner.command_seconds,runner.deadline),(45,1060))


if __name__ == '__main__':
    unittest.main()

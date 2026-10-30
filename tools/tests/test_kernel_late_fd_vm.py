"""Raw UART and pure compiled-parser boundaries, never a local kernel run."""
import hashlib
from pathlib import Path
import unittest

from tools import host_stream_kernel_late_fd_vm as late
from tools import host_stream_kernel_vm_image as image
from tools.host_stream_kernel_cleanup_native import OWNED, function


def serial():
    def snapshot(name, state, fields):
        return (f'LSFVM1 snapshot={name} state={state} error=0'+''.join(
            f' field{i}={value}' for i,value in enumerate(fields))).encode()
    return b'\r\n'.join((b'LSFVM1 boot=constructor-only production-sockets=disabled',
        snapshot('opened',0,[0,0,0,0,0,0,2,0,0,0]),
        snapshot('ready',2,[3,0,0,1,1,0,17,0,0,0]),
        b'[    2.123456] '+late.HANDOFF,
        b'[    2.234567] '+image.PHYSICAL_MARKER,
        b'[    2.345678] '+late.OUTSIDE,late.LATE_CHECK))+b'\r\n'


class KernelLateFdVm(unittest.TestCase):
    def test_actual_ordered_transitions_preserve_raw_identity_without_synthetic_child_snapshot(self):
        raw=serial()
        observed=late.serial_observation(raw)
        self.assertTrue(observed['lateFdCollection'])
        self.assertTrue(observed['rootFinalFree'])
        self.assertFalse(observed['pendingFdHandoff']['requestReturned'])
        self.assertTrue(observed['physicalReturn']['outsideKthreaddCollector'])
        self.assertEqual(set(observed['snapshots']), {'opened','ready'})
        self.assertEqual(observed['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(observed['bytes'],len(raw))
        self.assertFalse(observed['physicalReturn']['nativeQuotaRelease'])

    def test_missing_duplicate_reordered_forged_or_shared_only_witnesses_refuse(self):
        raw=serial()
        for marker in (late.HANDOFF,image.PHYSICAL_MARKER,late.OUTSIDE):
            for changed in (raw.replace(marker,b''),raw+marker+b'\n',
                    raw.replace(marker,b'private-prefix '+marker),
                    raw.replace(b'[    2.',b'[invalid.'),
                    raw.replace(b'pending=1',b'pending=0'),raw+b'Kernel panic',
                    raw+bytes(image.MAX_SERIAL)):
                with self.subTest(marker=marker, size=len(changed)), self.assertRaises(ValueError):
                    late.serial_observation(changed)
        for first,second in ((late.HANDOFF,image.PHYSICAL_MARKER),
                (image.PHYSICAL_MARKER,late.OUTSIDE)):
            changed=raw.replace(first,b'TEMP_MARKER').replace(second,first).replace(b'TEMP_MARKER',second)
            with self.assertRaises(ValueError):late.serial_observation(changed)
        with self.assertRaises(ValueError):late.serial_observation(late.LATE_CHECK)

    def test_pid1_completion_may_precede_delayed_kernel_uart_with_independent_orders(self):
        lines=serial().splitlines()
        for reordered in (lines[:5]+[lines[6],lines[5]],
                lines[:3]+[lines[6]]+lines[3:6]):
            raw=b'\r\n'.join(reordered)+b'\r\n'
            observed=late.serial_observation(raw)
            self.assertTrue(observed['physicalReturn']['kernelMarkersOrdered'])
            self.assertTrue(observed['physicalReturn']['independentPid1UartOrder'])
            self.assertEqual(observed['sha256'],hashlib.sha256(raw).hexdigest())
        for wrong in (lines[:3]+[lines[6],lines[4],lines[3],lines[5]],
                [lines[0],lines[2],lines[1]]+lines[3:]):
            with self.assertRaises(ValueError):
                late.serial_observation(b'\r\n'.join(wrong)+b'\r\n')

    def test_actual_prebirth_and_ready_field_refusals_are_retained(self):
        raw=serial()
        for old,new in ((b'snapshot=opened state=0',b'snapshot=opened state=2'),
                (b'snapshot=ready state=2',b'snapshot=ready state=1'),
                (b'field0=3',b'field0=7'),(b'field3=1',b'field3=2'),
                (b'field4=1',b'field4=0'),(b'field6=17',b'field6=257'),
                (b'field8=0',b'field8=1'),(b'field9=0',b'field9=4')):
            with self.subTest(old=old), self.assertRaises(ValueError):late.serial_observation(raw.replace(old,new))

    def test_only_explicit_late_compile_selector_changes_source_and_both_modes_keep_budget(self):
        probe=(OWNED/'constructor-vm-init.c').read_bytes()
        selected=late.late_probe_source(probe)
        self.assertEqual(selected,late.SELECTOR+probe)
        with self.assertRaises(ValueError):late.late_probe_source(selected)
        with self.assertRaises(ValueError):late.late_probe_source(b'foreign PID1')
        self.assertEqual(late.BOOT_SECONDS*2,image.VM_SECONDS)
        with self.assertRaises(ValueError):late.authenticate_printk(b'foreign printk implementation')
        owner=(OWNED.parents[2]/'tools/qualify_host_stream_kernel_vm.py').read_text()
        self.assertIn("late.authenticate_printk(\n            original_inputs['kernel/printk/printk.c'])",owner)
        self.assertIn('stage = \'isolated-late-fd-vm\'',owner)
        self.assertIn("'--kmsg-control'",owner)

    def test_hosted_compiled_controls_use_pure_leaf_before_all_guest_side_effects(self):
        probe=(OWNED/'constructor-vm-init.c').read_text()
        for prefix in ('static int log_number(', 'static int log_marker(',
                'static int observe_log_record(', 'static int kmsg_controls('):
            body=function(probe,prefix)
            for forbidden in ('check(', 'finish(', 'reboot(', 'mount(', 'open(',
                    'read(', 'poll(', 'now_ns(', 'sleep(', 'getpid('):
                self.assertNotIn(forbidden,body)
        main=function(probe,'int main(')
        self.assertLess(main.index('return kmsg_controls()'),main.index('getpid() != 1'))
        self.assertLess(main.index('getpid() != 1'),main.index('mount('))
        self.assertIn('cases != 22',probe)
        self.assertIn(late.COMPILED_CONTROLS.decode().strip(),probe)
        self.assertNotIn(image.PHYSICAL_MARKER,probe.encode())

    def test_real_event_wait_is_nonblocking_bounded_and_never_echoes_kernel_messages(self):
        probe=(OWNED/'constructor-vm-init.c').read_text()
        main=function(probe,'int main(')
        self.assertIn('O_RDONLY | O_NONBLOCK | O_CLOEXEC',main)
        self.assertLess(main.index('SEEK_END'),main.index('pending-descriptor-close'))
        self.assertLess(main.index('wait_outside_collector(log_fd)'),main.index('actual-pending-fd-retirement-root-release-check'))
        waiter=function(probe,'static void wait_outside_collector(')
        self.assertIn('20000000000u',waiter)
        self.assertIn('char record[4096]',waiter)
        self.assertIn('poll(&poll_fd, 1, millis)',waiter)
        self.assertLess(waiter.index('outside-collector-read-deadline'),
            waiter.index('observe_log_record(&state'))
        self.assertIn('outside-collector-completion-deadline',waiter)
        self.assertIn('errno == EAGAIN',waiter)
        self.assertIn('POLLERR | POLLHUP | POLLNVAL',waiter)
        record=function(probe,'static int observe_log_record(')
        self.assertIn('state->records >= 128',record)
        self.assertIn('state->total > 65536',record)
        marker=function(probe,'static int log_marker(')
        self.assertIn('length > 4096',marker)
        self.assertIn('priority <= 7',marker)
        self.assertIn("*cursor == '-'",marker)
        self.assertIn('++extensions > 16',marker)
        for forbidden in ('printf(', 'puts(', 'nanosleep(', 'sleep('):
            self.assertNotIn(forbidden,waiter)


if __name__=='__main__':unittest.main()

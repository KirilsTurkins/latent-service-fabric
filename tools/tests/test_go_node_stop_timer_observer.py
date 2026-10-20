"""Only actual closed native success labels can supply this diagnostic source."""
from pathlib import Path
import unittest

from tools import go_node_stop_timer_observer as probe


class GoNodeStopTimerObserver(unittest.TestCase):
    def test_actual_closed_events_retain_counts_but_never_claim_stop_qualification(self):
        raw = (probe.PREFIX + b'|pending|start-accepted|1|2|0|1\n' +
               probe.PREFIX + b'|pending|next-entered|2|2|1|1\n' +
               probe.PREFIX + b'|drain|root-close|3|2|1|1\n')
        value = probe.observe(raw)
        self.assertEqual(value['status'], 'observed')
        self.assertEqual([row['event'] for row in value['records']],
            ['start-accepted', 'next-entered', 'root-close'])
        self.assertEqual(value['records'][1], {'mode': 'pending', 'event': 'next-entered',
            'sequence': 2, 'tasks': 2, 'waits': 1, 'timers': 1})
        self.assertFalse(value['qualification'])

    def test_empty_disabled_or_unrelated_stderr_is_not_positive_evidence(self):
        for raw in (b'', b'ordinary-owned-stderr\n', b'LSF-JAVA-CONTROL-REFUSAL-V1 ignored\n'):
            value = probe.observe(raw)
            self.assertEqual(value['status'], 'not-observed')
            self.assertEqual(value['records'], [])
            self.assertFalse(value['qualification'])

    def test_unknown_or_private_fields_and_labels_are_rejected_without_projection(self):
        good = b'|pending|next-entered|1|2|1|1'
        for suffix in (good + b'|private-url', good.replace(b'pending', b'private-activation'),
                       good.replace(b'next-entered', b'host-completed'), good.replace(b'1|2', b'0|2')):
            value = probe.observe(probe.PREFIX + suffix + b'\n')
            self.assertEqual(value['status'], 'invalid-marker')
            self.assertEqual(value['records'], [])
            self.assertNotIn('private', str(value))

    def test_noncanonical_or_out_of_profile_counts_and_duplicate_sequences_are_refused(self):
        good = probe.PREFIX + b'|pending|next-entered|1|2|1|1\n'
        for raw in (good.replace(b'|1|2', b'|01|2'), good.replace(b'|1|2', b'|16|2'),
                    good.replace(b'|2|1|1', b'|17|1|1'), good.replace(b'|2|1|1', b'|2|5|1'),
                    good.replace(b'|2|1|1', b'|2|1|3'), good + good):
            self.assertEqual(probe.observe(raw)['status'], 'invalid-marker')

    def test_overflow_is_closed_failure_even_with_all_preceding_positive_labels(self):
        raw = probe.PREFIX + b'|pending|start-accepted|1|2|0|1\n' + probe.PREFIX + b'|overflow\n'
        value = probe.observe(raw)
        self.assertEqual(value['status'], 'overflow')
        self.assertTrue(value['overflow'])
        self.assertFalse(value['qualification'])
        self.assertEqual(probe.observe(raw + probe.PREFIX + b'|overflow\n')['status'], 'invalid-marker')

    def test_capture_and_per_process_record_limits_are_finite_and_fail_closed(self):
        self.assertEqual(probe.observe(b'x' * 262145)['status'], 'invalid-source')
        self.assertEqual(probe.observe('not-bytes')['status'], 'invalid-source')
        row = probe.PREFIX + b'|overflow\n'
        self.assertEqual(probe.observe(row * 17)['status'], 'invalid-marker')
        self.assertEqual(probe.observe(probe.PREFIX + b'x' * 129)['status'], 'invalid-marker')
        raw = b''.join(probe.PREFIX + b'|pending|next-entered|' + str(index).encode() + b'|2|1|1\n'
            for index in range(1, 10))
        self.assertEqual(probe.observe(raw)['status'], 'invalid-marker')

    def test_reordered_output_uses_unique_native_sequences_without_inventing_events(self):
        raw = probe.PREFIX + b'|pending|next-entered|2|2|1|1\n' + probe.PREFIX + b'|pending|start-accepted|1|2|0|1\n'
        self.assertEqual([row['sequence'] for row in probe.observe(raw)['records']], [1, 2])

    def test_host_success_hooks_follow_real_admission_and_leave_original_error_paths(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / 'crates/latent-wasmtime/src/host/runtime.rs').read_text()
        start = source[source.index('"timer-start",'):source.index('sync!("timer-stop"')]
        self.assertLess(start.index('RuntimeTimer::new('), start.index('table.timers.push(timer);'))
        self.assertLess(start.index('table.timers.push(timer);'), start.index('TimerEvent::StartAccepted'))
        next_source = source[source.index('fn prepare_timer_next('):source.index('impl WaitingTimer')]
        self.assertLess(next_source.index('timer.begin_wait()?'), next_source.index('TimerEvent::NextEntered'))
        close = source[source.index('sync!("close"'):source.index('sync!("observe"')]
        self.assertLess(close.index('table.runtime.close();'), close.index('TimerEvent::RootClose'))
        self.assertIn('std::mem::size_of::<Self>()', source)
        observer = (root / 'crates/latent-wasmtime/src/host/runtime/positive_timer_observer.rs').read_text()
        self.assertIn('static BUDGET: Budget', observer)
        self.assertIn('const MAXIMUM_EVENTS: u8 = 15;', observer)
        self.assertIn('const MAXIMUM_MODE_RECORDS: u8 = 8;', observer)
        self.assertNotIn('format!(', observer)
        self.assertNotIn('eprintln!', observer)


if __name__ == '__main__':
    unittest.main()

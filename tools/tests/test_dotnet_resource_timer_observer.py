"""The unchanged private observer never acquires .NET authority or widens limits."""
import unittest
from tools import dotnet_resource_timer_observer as reader
from tools import go_node_stop_timer_observer as original


class ManagedTimerObserver(unittest.TestCase):
    def test_managed_profile_accepts_its_exact_counts_without_changing_original_go_reader(self):
        raw=reader.PREFIX+b'|pending|next-entered|1|8|16|8\n'
        value=reader.observe(raw)
        self.assertEqual(value['status'],'observed')
        self.assertEqual(value['records'],[{'mode':'pending','event':'next-entered','sequence':1,
            'tasks':8,'waits':16,'timers':8}])
        self.assertEqual(original.observe(raw)['status'],'invalid-marker')
        self.assertFalse(value['qualification']);self.assertFalse(value['goProgrammeExecutionClaimed'])
        self.assertEqual(reader.ENVIRONMENT,original.ENVIRONMENT)

    def test_real_wait_for_pending_label_is_explicit_and_old_reader_refuses_it(self):
        raw=reader.PREFIX+b'|pending|wait-pending|1|1|1|1\n'
        self.assertEqual(reader.observe(raw)['records'][0]['event'],'wait-pending')
        self.assertEqual(original.observe(raw)['status'],'invalid-marker')

    def test_unknown_malformed_duplicate_overflow_and_foreign_counts_refuse(self):
        valid=reader.PREFIX+b'|pending|start-accepted|1|1|0|1\n'
        negatives=[valid+valid,valid.replace(b'|1|1|0|1',b'|1|9|0|1'),
            valid.replace(b'|1|1|0|1',b'|1|1|17|1'),valid.replace(b'|1|1|0|1',b'|1|1|0|9'),
            valid.replace(b'|pending|',b'|foreign|'),valid.replace(b'|1|1|0|1',b'|01|1|0|1'),
            valid.replace(b'|start-accepted|',b'|unreviewed|')]
        for raw in negatives:
            with self.subTest(raw=raw):self.assertEqual(reader.observe(raw)['status'],'invalid-marker')
        self.assertEqual(reader.observe(valid+reader.PREFIX+b'|overflow\n')['status'],'overflow')

    def test_empty_unbounded_and_marker_capacity_are_closed(self):
        self.assertEqual(reader.observe(b'ordinary nonmarker diagnostics\n')['status'],'not-observed')
        self.assertEqual(reader.observe(b'x'*(reader.MAXIMUM_STDERR+1))['status'],'invalid-source')
        raw=b''.join(reader.PREFIX+b'|pending|root-close|'+str(i).encode()+b'|0|0|0\n' for i in range(1,10))
        self.assertEqual(reader.observe(raw)['status'],'invalid-marker')


if __name__=='__main__':unittest.main()

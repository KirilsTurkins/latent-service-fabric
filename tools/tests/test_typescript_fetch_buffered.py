"""The separate zero-contact programme must retain original limits and witnesses."""
import inspect
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from tools import typescript_fetch_buffered as buffered
from tools import qualify_typescript_fetch_conformance as qualification
from tools.phase2_operator_process import WorkflowError
from tools.standard_http.peer import Peer


class BufferedFetchTests(unittest.TestCase):
    def test_original_manifest_and_source_are_preserved_except_exact_probe_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=buffered.base.project(root/'original')
            actual=buffered.project(root/'buffered')
            self.assertEqual((actual/'capsule-project.json').read_bytes(),(original/'capsule-project.json').read_bytes())
            self.assertEqual((actual/'src/main.ts').read_bytes(),(buffered.ROOT/buffered.SOURCE).read_bytes())
            self.assertEqual(json.loads((actual/'sdk-lock.json').read_bytes())['template']['sourceDigest'],
                buffered.digest((actual/'src/main.ts').read_bytes()))

    def test_only_the_explicit_separate_selection_can_replace_full_network_cases(self):
        self.assertIs(inspect.signature(qualification.execute).parameters['buffered_only'].default,False)
        self.assertIs(inspect.signature(qualification.qualify).parameters['buffered_only'].default,False)
        rows=buffered.vectors()
        self.assertEqual(len(rows),5)
        self.assertEqual([row[1] for row in rows],list(range(5)))
        self.assertTrue(all(row[4]==0 for row in rows))
        self.assertEqual(rows[0][3],'windows:65536,65536,1:copied:no-prefetch')
        self.assertEqual(rows[1][3],'cancelled:one-window:remainder-unread')

    def test_real_empty_peer_report_cannot_hide_contact_or_mutation(self):
        with closing(Peer(b'Bearer '+b'0'*64,maximum_seconds=5)) as peer:
            peer.close()
            value=peer.observation()
        self.assertEqual(buffered.peer_evidence(value),value)
        for field in ('startedRequests','acceptedConnections','committedMutations','rejectedRequests'):
            with self.subTest(field=field),self.assertRaises((WorkflowError,ValueError)):
                buffered.peer_evidence({**value,field:1})


if __name__=='__main__':unittest.main()

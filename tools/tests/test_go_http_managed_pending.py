"""Closed positive native witnesses and real held-header peer controls."""
import copy
from contextlib import closing
from pathlib import Path
import socket
import unittest

from tools import go_http_managed_pending as pending
from tools import go_http_tenant_node as node
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.standard_http.peer import Peer


def record(event,sequence,tasks=10,waits=0,timers=1,mode='pending'):
    return pending.PREFIX+f'|{mode}|{event}|{sequence}|{tasks}|{waits}|{timers}\n'.encode()


def accepted():
    return record('start-accepted',1)+record('next-entered',2,waits=1)+record('start-accepted',3)+record('next-entered',4,waits=1)


def observations():
    inventory={'topology':{'available':True,'complete':True,
        'entries':[{'name':name,'activeCount':'1'} for name in pending.LIVE]},'queueDepth':'0'}
    usage={'nextPageToken':None,'tenantUsage':{'scope':'tenant','unavailable':[],
        'counters':{'calls':'2','sessions':'1'}},'nodeUsage':{'scope':'node','unavailable':[],
        'counters':{'broker_calls':'2','pool_active_connections':'1','pool_running_requests':'1'}}}
    return inventory,usage


class ManagedGoHttpPendingControls(unittest.TestCase):
    def test_owned_deadline_derivation_refuses_unknown_or_repeated_preimages(self):
        from tools import go_http_tenant_fixture as fixture
        source=(ROOT/fixture.LIBRARY_SOURCE).read_bytes()
        changed=fixture.managed_deadline(source)
        self.assertEqual(changed.count(fixture.MANAGED_DEADLINE),1)
        self.assertEqual(changed.replace(fixture.MANAGED_DEADLINE,fixture.DEADLINE),source)
        for bad in (source.replace(fixture.DEADLINE,b''),source+fixture.DEADLINE,changed):
            with self.subTest(bad=len(bad)),self.assertRaises(ValueError):fixture.managed_deadline(bad)

    def test_three_cases_use_both_original_client_deadlines_and_fresh_cross_tenant_state(self):
        rows=pending.cases(node.DOMAIN)
        self.assertEqual(len(rows),3)
        self.assertEqual([(row[0],row[2],row[4]) for row in rows],
            [('examples',4,'cancelled'),('foreign',104,'cancelled'),('examples',0,node.DOMAIN)])
        self.assertEqual([row[3] for row in rows],['/conformance/hold/headers']*2+['/conformance/json'])
        self.assertEqual(sum(row[5] for row in rows),3)
        self.assertEqual(len(node.cases()),19)
        self.assertEqual(sum(row[5] for row in node.cases()),15)

    def test_successful_next_requires_second_owned_timer_and_application_beyond_eight_maintenance_tasks(self):
        observed=pending.positive(accepted(),'node-stop-pending')
        self.assertEqual(observed['maintenanceTasks'],8)
        self.assertEqual(observed['applicationTasksAtLeast'],2)
        self.assertEqual(observed['lastEntered']['waits'],1)
        for source in (b'',record('start-accepted',1),record('start-accepted',1)+record('next-entered',2,waits=1),
                accepted().replace(b'|10|1|1',b'|8|1|1'),accepted().replace(b'|10|1|1',b'|10|0|1'),
                accepted().replace(b'|10|1|1',b'|10|1|0'),accepted().replace(b'|10|1|1',b'|10|1|2')):
            with self.subTest(source=source):self.assertIsNone(pending.positive(source,'node-stop-pending'))
        with self.assertRaises(WorkflowError):pending.positive(accepted()+record('root-close',5),'node-stop-pending')
        with self.assertRaises(WorkflowError):pending.positive(accepted(),'arbitrary-activation')

    def test_unknown_private_extra_overflow_missing_duplicate_and_out_of_profile_records_refuse(self):
        bad=(pending.PREFIX+b'|overflow\n',record('raw-private-message',1),record('start-accepted',1,mode='other'),
            record('start-accepted',1,tasks=17),record('start-accepted',1,waits=17),record('start-accepted',1,timers=9),
            record('start-accepted',2),record('start-accepted',1)*2,
            record('start-accepted',1).replace(b'|1|10',b'|01|10'),
            record('start-accepted',1).replace(b'\n',b'|extra\n'))
        for source in bad:
            with self.subTest(source=source),self.assertRaises(WorkflowError):pending.observe(source)
        with self.assertRaises(WorkflowError):pending.observe(b'x'*(pending.MAXIMUM_STDERR+1))
        with self.assertRaises(WorkflowError):pending.observe('not bytes')
        with self.assertRaises(WorkflowError):pending.observe(b''.join(record('start-accepted',i) for i in range(1,10)))

    def test_live_pipe_partial_record_cannot_be_a_positive_witness_and_full_two_mode_sequence_is_retained(self):
        source=accepted()
        for count in range(1,len(source.splitlines()[-1])):
            self.assertIsNone(pending.positive(source[:-count],'node-stop-pending'))
        both=source+record('root-close',5)+record('start-accepted',6,mode='drain')
        self.assertEqual([row['sequence'] for row in pending.observe(both)['records']],list(range(1,7)))
        self.assertEqual(pending.observe(b'ordinary node stderr\n'+source)['records'],pending.observe(source)['records'])

    def test_post_retirement_or_non_http_broker_work_cannot_replace_live_owned_http(self):
        inventory,usage=observations()
        observed=pending.live(inventory,usage,accepted(),'node-stop-pending')
        self.assertEqual(observed['physicalOwners'],dict.fromkeys(pending.LIVE,1))
        self.assertFalse(observed['postRetirementOnlyProof'])
        for key in ('broker_calls','pool_active_connections','pool_running_requests'):
            changed=copy.deepcopy(usage);changed['nodeUsage']['counters'][key]='0'
            self.assertIsNone(pending.live(inventory,changed,accepted(),'node-stop-pending'))
        changed=copy.deepcopy(inventory);changed['topology']['entries'][0]['activeCount']='0'
        self.assertIsNone(pending.live(changed,usage,accepted(),'node-stop-pending'))
        for side in ('tenantUsage','nodeUsage'):
            changed=copy.deepcopy(usage);changed[side]['unavailable']=['unavailable']
            with self.assertRaises(WorkflowError):pending.live(inventory,changed,accepted(),'node-stop-pending')
        changed=copy.deepcopy(inventory);changed['queueDepth']='1'
        with self.assertRaises(WorkflowError):pending.live(changed,usage,accepted(),'node-stop-pending')
        changed=copy.deepcopy(usage);changed['nextPageToken']='next'
        with self.assertRaises(WorkflowError):pending.live(inventory,changed,accepted(),'node-stop-pending')

    def test_exact_owning_workflow_reuses_products_and_selects_actual_managed_guest_without_native_build(self):
        from tools.ci_lane_inventory import workflow_model
        original=workflow_model((ROOT/'.github/workflows/go-http-tenant-catalogue.yml').read_text())
        selected=workflow_model((ROOT/'.github/workflows/go-http-managed-accounting.yml').read_text())
        steps=selected['jobs']['tenants']['steps']
        normal_namespace=next(row['run'] for row in original['jobs']['tenants']['steps']
            if row.get('name')=='Install captured Go compiler namespace')
        self.assertEqual(next(row['run'] for row in steps if row.get('name')=='Install captured Go compiler namespace'),normal_namespace)
        run=[row['run'] for row in steps if 'tools/qualify_go_http_tenants.py' in row.get('run','')]
        self.assertEqual(len(run),1);self.assertTrue(run[0].endswith('--managed-runtime'))
        self.assertEqual(sum('tools/wait_runtime_native_products.py --output' in row.get('run','') for row in steps),1)
        self.assertNotIn('cargo ',str(steps));self.assertNotIn('build_native_runtime',str(steps))

    def test_real_peer_retains_unreleased_header_gate_without_response_for_both_clients(self):
        token=b'Bearer '+b'1'*64
        for tenant in node.TENANTS:
            with closing(Peer(token,maximum_seconds=300)) as peer:
                for who,_name,_mode,path,_expected,_contacts in pending.cases(node.DOMAIN):
                    if who!=tenant:continue
                    with socket.create_connection(('127.0.0.1',peer.origin()['port']),timeout=2) as stream:
                        stream.sendall((f'GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{peer.origin()["port"]}\r\n'
                            'Authorization: '+token.decode()+'\r\nConnection: close\r\n\r\n').encode())
                        for _ in range(32):
                            peer.poll(.01)
                            if peer.rows[-1]['state'] in {'closed','held-headers'}:break
                        self.assertIn(peer.rows[-1]['state'],{'closed','held-headers'})
                    for _ in range(32):
                        peer.poll(.01)
                        if peer.rows[-1]['state']=='closed':break
                value=peer.close()
            pending.peer_outcome(value,tenant,node.DOMAIN)
            bad=copy.deepcopy(value)
            gate=next(row for row in bad['events'] if row['kind']=='gate-pending');gate['kind']='gate-released'
            with self.assertRaises(WorkflowError):pending.peer_outcome(bad,tenant,node.DOMAIN)
            bad=copy.deepcopy(value);bad['requests'][0]['responseBytesWritten']=1
            with self.assertRaises(WorkflowError):pending.peer_outcome(bad,tenant,node.DOMAIN)


if __name__=='__main__':unittest.main()

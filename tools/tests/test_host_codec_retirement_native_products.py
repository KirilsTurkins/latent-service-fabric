"""Closed177 schema models; no artifact download, native execution or guest claim."""
import copy
import subprocess
import unittest
from unittest.mock import patch

from tools import host_codec_retirement_native_products as owner
from tools import sdk_native_products_reader as original
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT
from tools.tests.test_host_codec_native_products_reader import model as original_model


def model():
    _, record, snapshot, native, materials = original_model()
    selected = owner.READER
    cargo = ['cargo', '--config', '/controlled/source/.cargo/managed-guest.toml']
    argv = [row['argv'] for row in record['commands'][:3]]
    for _, package, needle, _ in selected.controls:
        command = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
        argv.extend([command + ['--list'], command + ['--test-threads=1']])
    record.update(sourceRevision=owner.SOURCE, controlCount=177,
        nativeCohort=owner.COHORT, wasmtimeAllocationCohort=owner.ALLOCATION_COHORT,
        scope=owner.SCOPE, controls={stage:list(cases) for stage,_,_,cases in selected.controls},
        commands=[{'stage':stage, 'argv':command, 'exitCode':0, 'seconds':.1,
            'logs':{stream:{'path':f'logs/{index:02d}-{stage}.{stream}.txt',
                'bytes':0, 'sha256':'sha256:'+'0'*64} for stream in ('stdout','stderr')}}
            for index,(stage,command) in enumerate(zip(selected.stages,argv))])
    return record, snapshot, native, materials


class HostCodecRetirementNativeProducts(unittest.TestCase):
    def test_literal77_is_the_only_extension_and_preserves_all_historical_defaults(self):
        selected = owner.READER
        self.assertEqual((len(selected.controls),sum(len(row[3]) for row in selected.controls),
            len(selected.recipe),len(selected.stages)),(37,177,22,77))
        self.assertEqual(selected.stages,owner.STAGES)
        self.assertEqual(selected.source,owner.SOURCE)
        with self.assertRaises(TypeError):
            owner._FrozenRetirementNativeProducts(source='3'*40)
        for stages in (owner.STAGES[:-1],owner.STAGES+('foreign-extra',),
                tuple(reversed(owner.STAGES)),owner.STAGES[:33]+('foreign-stage',)+owner.STAGES[34:]):
            with self.subTest(stages=stages), self.assertRaisesRegex(WorkflowError,'frozen-configuration'):
                original.FrozenNativeProducts.__init__(object.__new__(owner._FrozenRetirementNativeProducts),
                    source=owner.SOURCE,run=owner.RUN,job=owner.JOB,artifact=owner.ARTIFACT,
                    receipts=owner.RECEIPTS,branch=owner.BRANCH,stages=stages)
        with self.assertRaisesRegex(WorkflowError,'frozen-configuration'):
            original.FrozenNativeProducts(source=owner.SOURCE,run=owner.RUN,job=owner.JOB,
                artifact=owner.ARTIFACT,receipts=owner.RECEIPTS,branch=owner.BRANCH,stages=owner.STAGES)
        for name in ('prepare','verify_prepared','extract','preflight','_official_artifact'):
            self.assertIs(getattr(type(selected),name),getattr(original.FrozenNativeProducts,name))

    def test_full_frozen_producer_digest_refuses_any_case_recipe_or_stage_rewrite(self):
        raw = subprocess.check_output(['git','show',owner.SOURCE+':tools/qualify_host_codec_native.py'],cwd=ROOT)
        self.assertEqual(owner.READER._producer_contract(raw),(owner.READER.controls,owner.READER.recipe))
        for invalid in (raw+b'\n',raw.replace(b'actual-native-only-cumulative-retirement',b'foreign-stage',1),
                raw.replace(b'concurrent_last_ordinary_and_physical_owners_settle_each_original_counter_once',b'foreign_control_',1),
                raw.replace(b'actual-streaming-table-shared-owner',b'foreign-stage',1),
                raw.replace(b'resource_table_native_backing_',b'foreign_control_',1),
                raw.replace(b'tools/build_process_signals.py',b'tools/foreign.py',1)):
            self.assertNotEqual(raw,invalid)
            with self.assertRaisesRegex(WorkflowError,'exact-frozen-producer'):
                owner.READER._producer_contract(invalid)

    def test_complete177_model_keeps_tail_command_stream_time_and_schema_guards(self):
        record,snapshot,native,materials = model()
        owner.READER.validate_record(record,snapshot,native,materials)
        for kind in ('missing','extra','reordered','altered','argv','exit','missing-stream','log-path',
                'log-overflow','total-stream-bytes','nonfinite','aggregate-time','source','native',
                'materials','scope','cohort','allocation-cohort','missing-allocation-cohort',
                'count-bool','product','guest-claim','extra-field'):
            bad = copy.deepcopy(record)
            if kind == 'missing': bad['commands'].pop()
            elif kind == 'extra': bad['commands'].append(copy.deepcopy(bad['commands'][-1]))
            elif kind == 'reordered': bad['commands'][-1],bad['commands'][-2] = bad['commands'][-2],bad['commands'][-1]
            elif kind == 'altered': bad['commands'][-1]['stage'] = 'foreign-stage'
            elif kind == 'argv': bad['commands'][-1]['argv'][-1] = '--ignored'
            elif kind == 'exit': bad['commands'][-1]['exitCode'] = 1
            elif kind == 'missing-stream': bad['commands'][-1]['logs'].pop('stderr')
            elif kind == 'log-path': bad['commands'][-1]['logs']['stdout']['path'] = '../foreign'
            elif kind == 'log-overflow': bad['commands'][-1]['logs']['stdout']['bytes'] = 4*1024**2+1
            elif kind == 'total-stream-bytes':
                for row in bad['commands']:
                    for log in row['logs'].values(): log['bytes'] = 16*1024**2//154+1
            elif kind == 'nonfinite': bad['commands'][-1]['seconds'] = float('nan')
            elif kind == 'aggregate-time':
                for row in bad['commands']: row['seconds'] = 1320/77+1
            elif kind == 'source': bad['sourceRevision'] = '3'*40
            elif kind == 'native': bad['source'] = {}
            elif kind == 'materials': bad['materials'] = {}
            elif kind == 'scope': bad['scope'] += '-foreign'
            elif kind == 'cohort': bad['nativeCohort'] = owner.ALLOCATION_COHORT
            elif kind == 'allocation-cohort': bad['wasmtimeAllocationCohort'] = owner.COHORT
            elif kind == 'missing-allocation-cohort': bad.pop('wasmtimeAllocationCohort')
            elif kind == 'count-bool': bad['controlCount'] = True
            elif kind == 'product': bad['products'].pop('latentd')
            elif kind == 'guest-claim': bad['signedQualification'] = True
            else: bad['foreign-field'] = True
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                owner.READER.validate_record(bad,snapshot,native,materials)

    def test_official_origin_keeps_exact_source_run_job_branch_event_and_artifact_pins(self):
        artifact = {**owner.ARTIFACT,'name':'host-codec-memory-'+owner.SOURCE,'expired':False,
            'workflow_run':{'id':owner.RUN,'head_sha':owner.SOURCE}}
        run = {'id':owner.RUN,'head_sha':owner.SOURCE,'path':'.github/workflows/host-codec-memory.yml',
            'event':'push','head_branch':owner.BRANCH,'status':'completed','conclusion':'success'}
        job = {'id':owner.JOB,'run_id':owner.RUN,'head_sha':owner.SOURCE,
            'name':owner.READER.job_name,'status':'completed','conclusion':'success'}
        replies = {f'actions/runs/{owner.RUN}':run,f'actions/jobs/{owner.JOB}':job,
            f'actions/runs/{owner.RUN}/artifacts?per_page=100':{'total_count':1,'artifacts':[artifact]}}
        with patch.object(original,'api',side_effect=replies.__getitem__):
            self.assertEqual(owner.READER._official_artifact(),artifact)
            for target,key,value in ((run,'head_sha','3'*40),(run,'id',1),
                    (run,'path','.github/workflows/sdk-native-products.yml'),(run,'head_branch','development'),
                    (run,'event','workflow_dispatch'),(job,'run_id',1),(job,'id',1),(job,'head_sha','3'*40),
                    (job,'name','foreign-job'),(artifact,'id',1),(artifact,'size_in_bytes',1),
                    (artifact,'digest','sha256:'+'f'*64)):
                old = target[key]
                target[key] = value
                with self.subTest(key=key,value=value), self.assertRaises(WorkflowError):
                    owner.READER._official_artifact()
                target[key] = old


if __name__ == '__main__':
    unittest.main()

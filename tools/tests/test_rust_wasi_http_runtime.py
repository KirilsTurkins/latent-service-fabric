"""Fail-closed source/oracle controls; no guest or native compilation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import qualify_rust_wasi_http_runtime as qualification
from tools import rust_wasi_http_runtime_node as node
from tools.rust_capsule_project import canonical,digest


class SourceAndNativeSeparation(unittest.TestCase):
    def test_actual_available_usage_list_and_all_original_owner_counters_are_required(self):
        path=Path(__file__).resolve().parents[2]/'docs/testing/evidence/rust-wasi-http-runtime-provider-counter-failure-2026-10-21.json'
        actual=json.loads(path.read_bytes())['observedNodeUsage']
        self.assertIsNot(actual['unavailable'],False) # exact retained payload: old reader RED
        client=Mock();client.call.return_value={'data':{'nodeUsage':actual}}
        self.assertEqual(node.usage(client,{'name':'controlled'})['nodeUsage'],actual)
        self.assertEqual(len(node.ACTIVE_COUNTERS),18)
        self.assertTrue(all(node.unsigned(actual['counters'][name])==0 for name in node.ACTIVE_COUNTERS))
        for kind in ('false','none','missing','unavailable','scope','counter','negative','boolean'):
            changed=copy.deepcopy(actual)
            if kind=='false':changed['unavailable']=False
            elif kind=='none':changed['unavailable']=None
            elif kind=='missing':changed['unavailable']={}
            elif kind=='unavailable':changed['unavailable']=['provider-io-no-retained-pool-owner']
            elif kind=='scope':changed['scope']='tenant'
            elif kind=='counter':changed['counters'].pop(node.ACTIVE_COUNTERS[0])
            elif kind=='negative':changed['counters'][node.ACTIVE_COUNTERS[0]]='-1'
            else:changed['counters'][node.ACTIVE_COUNTERS[0]]=True
            client.call.return_value={'data':{'nodeUsage':changed}}
            with self.subTest(kind=kind),self.assertRaises(Exception):node.usage(client,{'name':'controlled'})

    def test_actual_output_guard_receipt_and_original_compiler_success_are_both_required(self):
        from tools.rust_capsule_build import RustExecutableOutputs
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'target';(target/'release/deps').mkdir(parents=True)
            (target/'release/deps/libcontrol.so').write_bytes(b'controlled original tool output')
            output=root/'output';output.mkdir()
            approval={'identity':'sha256:'+'a'*64}
            guard=RustExecutableOutputs(target,output,approval['identity'])
            receipt=json.loads(guard.path.read_bytes())
            self.assertEqual(set(receipt),{'formatVersion','approvalIdentity','cleanup','hermetic','outputs'})
            with self.assertRaises(KeyError):receipt['compilerCommandSucceeded']
            commands=[{'stage':'compile','exitCode':0}]
            qualification.verify_executable_outputs(receipt,approval,commands)
            for key,value in (('formatVersion',True),('approvalIdentity','sha256:'+'b'*64),
                ('cleanup','uncertain'),('hermetic',True),('outputs',{})):
                changed=copy.deepcopy(receipt);changed[key]=value
                with self.subTest(key=key),self.assertRaises(Exception):
                    qualification.verify_executable_outputs(changed,approval,commands)
            for changed_commands in ([],[{'stage':'compile','exitCode':1}],
                    [{'stage':'rust-http-compiler-root-compile','exitCode':0}],commands+commands):
                with self.subTest(commands=changed_commands),self.assertRaises(Exception):
                    qualification.verify_executable_outputs(receipt,approval,changed_commands)
            changed=copy.deepcopy(receipt)
            changed['outputs']['release/deps/libcontrol.so']['size']=64*1024**2+1
            with self.assertRaises(Exception):qualification.verify_executable_outputs(changed,approval,commands)
            changed=copy.deepcopy(receipt);changed['compilerCommandSucceeded']=True
            with self.assertRaises(Exception):qualification.verify_executable_outputs(changed,approval,commands)

    def test_backend_producer_origin_requires_exact_successful_source_job_and_artifact(self):
        from tools import rust_wasi_http_backend_products as backend
        run={'id':backend.RUN,'head_sha':backend.SOURCE,'head_branch':'feat/rust-wasi-http-profile-20261021',
            'event':'push','path':'.github/workflows/rust-wasi-http-runtime.yml','status':'completed','conclusion':'success'}
        job={'id':backend.JOB,'run_id':backend.RUN,'head_sha':backend.SOURCE,'status':'completed','conclusion':'success'}
        artifact={**backend.ARTIFACT,'expired':False,'name':'rust-wasi-http-backend-'+backend.SOURCE,
            'workflow_run':{'id':backend.RUN,'head_sha':backend.SOURCE,'head_branch':run['head_branch'],
                'repository_id':1337591365,'head_repository_id':1337591365}}
        self.assertFalse(backend.validate_origin(run,job,artifact)['signedQualification'])
        for selected,key,value in (('run','head_sha','0'*40),('run','event','workflow_dispatch'),
            ('job','conclusion','failure'),('job','run_id',1),('artifact','expired',True),
            ('artifact','digest','sha256:'+'0'*64),('artifact','size_in_bytes',1),('artifact','id',1)):
            values={'run':copy.deepcopy(run),'job':copy.deepcopy(job),'artifact':copy.deepcopy(artifact)}
            values[selected][key]=value
            with self.subTest(selected=selected,key=key),self.assertRaises(Exception):
                backend.validate_origin(values['run'],values['job'],values['artifact'])
        changed=copy.deepcopy(artifact);changed['workflow_run']['head_repository_id']=1
        with self.assertRaises(Exception):backend.validate_origin(run,job,changed)

    def test_restored_backend_members_and_composer_are_bound_before_they_can_execute(self):
        from tools import rust_wasi_http_backend_products as backend
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'component-composer').mkdir()
            names={'rust-wasi-http-runtime.wasm','raw-runtime.wasm','reference.wit.json','adapter.wit.json'}
            for name in names:(root/name).write_bytes(('controlled '+name).encode())
            (root/'component-composer/wac').write_bytes(b'controlled unexecuted composer')
            sources=b'controlled original source inventory'
            (root/'source-inputs.json').write_bytes(sources)
            def row(name):
                raw=(root/name).read_bytes();return {'name':name,'digest':digest(raw),'size':len(raw)}
            record={'sourceRows':110,'sourceDigest':digest(sources),'qualification':'compiled-adapter-only',
                'signedQualification':False,'files':{name:row(name) for name in names},
                'tools':{'component-composer':row('component-composer/wac')}}
            raw=canonical(record);(root/'INSTALL-COMPLETE.json').write_bytes(raw)
            pins={'INSTALL-COMPLETE.json':{'sha256':digest(raw),'bytes':len(raw)},
                'source-inputs.json':{'sha256':digest(sources),'bytes':len(sources)}}
            with patch.object(backend,'RECEIPTS',pins):
                self.assertFalse(backend.verify_materials(root)['producerReceiptRewritten'])
                for name in (*names,'component-composer/wac','source-inputs.json','INSTALL-COMPLETE.json'):
                    path=root/name;original=path.read_bytes();path.write_bytes(original+b'tampered')
                    with self.subTest(name=name),self.assertRaises(Exception):backend.verify_materials(root)
                    path.write_bytes(original)

    def test_catalogue_absence_is_bound_to_complete_actual_source_and_recipe_names(self):
        source={'src/lib.rs':{},'vendor/lsf/sdk/src/lib.rs':{'digest':'original-sdk','size':7},'sdk-lock.json':{}}
        sdk={'sdk/src/lib.rs':source['vendor/lsf/sdk/src/lib.rs']}
        recipe={'sdk/wasi-http-runtime/types.rs':{},'tools/rust_capsule_build.py':{}}
        proof=qualification.catalogue_inputs(source,recipe,sdk)
        self.assertEqual(proof['catalogueDataInputs'],[])
        self.assertEqual(proof['sourceInputNames'],sorted(source))
        self.assertEqual(proof['recipeInputNames'],sorted(recipe))
        self.assertEqual(proof['sdkInputNames']['captured-source'],['vendor/lsf/sdk/src/lib.rs'])
        self.assertFalse(proof['repositoryPublicationDataDeleted'])
        for selected in ('source','recipe'):
            for name in ('docs/compatibility-catalogue/v3/evidence/entry.json','catalogue.json','../hidden','/absolute','a\\b'):
                a=copy.deepcopy(source);b=copy.deepcopy(recipe)
                (a if selected=='source' else b)[name]={}
                with self.subTest(selected=selected,name=name),self.assertRaises(Exception):
                    qualification.catalogue_inputs(a,b,sdk)
        for mutate in ('missing','extra','changed'):
            altered=copy.deepcopy(sdk)
            if mutate=='missing':altered.clear()
            if mutate=='extra':altered['unlisted']={}
            if mutate=='changed':altered['sdk/src/lib.rs']['size']=8
            with self.subTest(mutate=mutate),self.assertRaises(Exception):
                qualification.catalogue_inputs(source,recipe,altered)

    def test_new_native_tuple_requires_exact_source_even_for_the_old_reviewed_formatter_pair(self):
        from tools import activation_stack_native_source as guard
        proof=json.loads((qualification.ROOT/'docs/testing/evidence/c-thread-native-rustfmt-2026-10-21.json').read_text())
        original=copy.deepcopy(guard.COMPILED)
        with patch.object(guard,'git_source_identity',return_value=copy.deepcopy(original)), \
                patch.object(guard,'source_identity',return_value=copy.deepcopy(original)):
            result=qualification.assert_current(qualification.ROOT)
        self.assertTrue(result['compiledSourceByteExact'])
        self.assertEqual(result['reviewedSourceChanges'],[])
        for selected in (proof['formattedConsumerSource'],dict(original,files=original['files']+1),{}):
            with self.subTest(selected=selected), \
                    patch.object(guard,'git_source_identity',return_value=copy.deepcopy(original)), \
                    patch.object(guard,'source_identity',return_value=selected), \
                    self.assertRaisesRegex(RuntimeError,'exact-current-source'):
                qualification.assert_current(qualification.ROOT)

    def test_only_the_reviewed_unlinked_frontend_pair_may_differ(self):
        # The newer historical C tuple already contains the reviewed frontend.
        # Its entire auxiliary manifest must now match, with no old-pair waiver.
        original={f'wit/unchanged-{i}.wit':{'sha256':'sha256:'+'1'*64,'bytes':3} for i in range(133)}
        original['tools/rust_capsule_build.py']={'sha256':'sha256:'+'2'*64,'bytes':4}
        current=copy.deepcopy(original)
        value=qualification.native_compatibility(original,current)
        self.assertEqual(value['unchangedAuxiliaryRows'],134)
        self.assertTrue(value['allAuxiliaryRowsCurrentAtProducerCompilation'])
        self.assertEqual(value['unlinkedFrontendChanges'],[])
        for mutate in ('new-source','new-WIT','missing','extra','old-frontend'):
            changed=copy.deepcopy(current)
            if mutate=='new-source':changed['tools/rust_capsule_build.py']['sha256']='sha256:'+'3'*64
            if mutate=='new-WIT':changed['wit/unchanged-0.wit']['bytes']=4
            if mutate=='missing':changed.pop('wit/unchanged-1.wit')
            if mutate=='extra':changed['unknown']={'sha256':'sha256:'+'3'*64,'bytes':1}
            if mutate=='old-frontend':changed['tools/rust_capsule_build.py']['bytes']=5
            with self.subTest(mutate=mutate),self.assertRaises(Exception):
                qualification.native_compatibility(original,changed)

    def test_unsupported_platform_refuses_before_output_or_product_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(qualification.sys,'platform','win32'):
            out=Path(temporary)/'absent'
            with self.assertRaisesRegex(Exception,'linux-python313'):
                qualification.qualify(Path('not-present'),Path('not-present'),out)
            self.assertFalse(out.exists())

    def test_each_original_core_namespace_must_remain_in_the_actual_selected_component(self):
        core=b'\0asm\x01\0\0\0'
        component=b'\0asm\x0d\0\x01\0'+b'\x01'+bytes([len(core)])+core
        projection={'root':False,'coreBytesUnchanged':True,'publicApplicationGraphUnchanged':True,
            'runtimeQualification':False,'cores':[{'sha256':digest(core),'bytes':len(core)}]}
        record={'schemaVersion':'latent.rust.http.exact-composition.v1','profile':qualification.PROFILE,
            'publicGraphUnchanged':True,'librarySourceRewritten':False,'signedExecutionQualification':False,
            'selectedComponentDigest':digest(component),'imports':sorted(qualification.AUTHORITY),
            'exports':['examples:greeting/api@1.0.0'],'originalCoreModulesRetained':1,
            'explicitAsyncPublicContract':[{'interface':'examples:greeting/api@1.0.0',
                'function':'greet','kind':'async-freestanding'}],
            'compilerRootRustBindingsAsync':False,'forwardingRootApplicationImportsExact':True,
            'internalIo':projection,'privateDrain':{**projection,'root':True}}
        adapter={'cores':[{'digest':digest(core),'size':len(core)}]}
        qualification.verify_composition(record,component,adapter)
        for mutate in ('private-leak','new-core','public-graph','duplicate-missing','claim-runtime',
                       'sync-contract','injected-executor','root-import-drift'):
            changed=copy.deepcopy(record)
            if mutate=='private-leak':changed['imports'].append('latent:rust-http-retirement/owner@0.1.0')
            if mutate=='new-core':changed['internalIo']['cores'][0]['sha256']='sha256:'+'0'*64
            if mutate=='public-graph':changed['publicGraphUnchanged']=False
            if mutate=='duplicate-missing':
                changed['internalIo']['cores']*=2;changed['originalCoreModulesRetained']=2
            if mutate=='claim-runtime':changed['privateDrain']['runtimeQualification']=True
            if mutate=='sync-contract':changed['explicitAsyncPublicContract'][0]['kind']='freestanding'
            if mutate=='injected-executor':changed['compilerRootRustBindingsAsync']=True
            if mutate=='root-import-drift':changed['forwardingRootApplicationImportsExact']=False
            with self.subTest(mutate=mutate),self.assertRaises(Exception):
                qualification.verify_composition(changed,component,adapter)


class RuntimeOracles(unittest.TestCase):
    def test_partial_collection_and_cleanup_failure_cannot_replace_the_primary_invocation_failure(self):
        import time
        class PrimaryFailure(RuntimeError):pass
        process=Mock();process.owner.exited.return_value=False;process.owner.finished=False
        process.drain.side_effect=PrimaryFailure('original owned controller failure')
        process.close.side_effect=OSError('injected cleanup refusal')
        peer=Mock();peer.observation.return_value={'acceptedConnections':0}
        peer.origin.return_value={'host':'127.0.0.1','port':12345}
        client=Mock();client.deadline=time.monotonic()+10
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            with patch.object(node,'selected_revision',return_value={}),patch.object(node,'start_call',return_value=process), \
                patch.object(node,'retain_partial',side_effect=OSError('injected collection refusal')):
                with self.assertRaisesRegex(PrimaryFailure,'original owned controller failure'):
                    node.invoke(client,Mock(),{'budget':{}},{'examples':peer,'foreign':peer},'examples',
                        'waki','alpha',node.cases()[0],None,output,'original')
            value=json.loads((output/'partial-retention-refused-original.json').read_bytes())
            self.assertEqual(value['collectionStatus'],'refused')
            self.assertFalse(value['qualification'])
            self.assertFalse(value['cliProcessReapedObserved'])
            self.assertNotIn('injected',json.dumps(value))
        with self.assertRaises(OSError):node.close_call(process,primary_failure=False)

    def test_pre_result_failure_keeps_bounded_actual_cli_bytes_without_inventing_completion(self):
        import base64
        process=Mock()
        process.authoring_activation='node-stop-pending'
        process.buffers=[bytearray(b'{"schemaVersion":"latent.cli.result.v1",'),bytearray(b'controlled public CLI stderr')]
        process.owner.finished=False
        def close():process.owner.finished=True
        process.close.side_effect=close
        native=Mock();native.buffers=[bytearray(),bytearray(b'unrelated native line\n'+node.TIMER_PREFIX+b'|pending|wait-pending|1|1|2|1\n')]
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            value=node.retain_partial(process,native,output,'original')
            self.assertFalse(value['qualification'])
            self.assertFalse(value['normalResultCompleted'])
            self.assertTrue(value['cliProcessReapedAfterCleanup'])
            self.assertEqual(base64.b64decode(value['streams']['stdout']['base64']),bytes(process.buffers[0]))
            self.assertEqual(value['streams']['stderr']['sha256'],digest(bytes(process.buffers[1])))
            self.assertEqual(len(value['nativeTimerRecords']),1)
            self.assertNotIn('unrelated',json.dumps(value))
            self.assertFalse(value['nativeTimerRecordsTruncated'])
            self.assertTrue((output/'partial-invocation-original.json').is_file())
            process.complete.assert_not_called()

    def test_real_library_diagnostics_discriminate_timeout_permission_json_and_opaque_stream_errors(self):
        def payload(client,phase,display,debug,**public):
            base=({'typedWasiErrorCode':None,'serdeJsonError':False} if client=='waki' else {
                'isBuilder':False,'isRequest':True,'isBody':False,'isDecode':False,'isTimeout':False,
                'isStatus':False,'serdeJsonError':False,'sourceDisplay':None})
            base.update(public)
            value={'phase':phase,'display':display,'debug':debug,'displayBytes':len(display.encode()),
                'debugBytes':len(debug.encode()),'truncated':False,'public':base}
            return 'library-error:'+json.dumps(value)
        cases=[('waki','error:timeout-option',payload('waki','send','failed to set connect_timeout','failed to set connect_timeout')),
            ('golem','error:timeout-option',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='set_first_byte_timeout')),
            ('waki','error:request-denied',payload('waki','send','ErrorCode::HttpRequestDenied','ErrorCode::HttpRequestDenied',typedWasiErrorCode='ErrorCode::HttpRequestDenied')),
            ('golem','error:request-denied',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='ErrorCode::HttpRequestDenied')),
            ('waki','error:reserved-header',payload('waki','send','HeaderError::Forbidden','HeaderError::Forbidden')),
            ('golem','error:reserved-header',payload('golem','send','error sending request','real upstream request debug',sourceDisplay='HeaderError::Forbidden')),
            ('waki','error:json-decode',payload('waki','json','expected value','Error("expected value", line: 1, column: 1)',serdeJsonError=True)),
            ('golem','error:json-decode',payload('golem','json','error decoding response body','real serde source debug',isRequest=False,isDecode=True,serdeJsonError=True))]
        for client,expected,value in cases:
            self.assertTrue(node.library_error(value,client,expected)['exactUnderlyingCategoryProven'])
            for mutate in ('truncated','count','phase','json-kind','permission-substitution'):
                changed=json.loads(value.removeprefix('library-error:'))
                if mutate=='truncated':changed['truncated']=True
                if mutate=='count':changed['debugBytes']+=1
                if mutate=='phase':changed['phase']='unknown'
                if mutate=='json-kind':changed['public']['serdeJsonError']=not changed['public']['serdeJsonError']
                if mutate=='permission-substitution':
                    changed['public']['serdeJsonError']=False
                    changed['debug']=changed['display']='HttpRequestDenied'
                    changed['debugBytes']=changed['displayBytes']=len('HttpRequestDenied')
                    changed['public']['sourceDisplay' if client=='golem' else 'typedWasiErrorCode']='HttpRequestDenied'
                    if expected=='error:request-denied':
                        changed['public']['sourceDisplay' if client=='golem' else 'typedWasiErrorCode']='InternalError(Some("latent-runtime-unavailable"))'
                if mutate=='json-kind' and expected in {'error:request-denied','error:reserved-header'}:continue
                with self.subTest(client=client,expected=expected,mutate=mutate),self.assertRaises(Exception):
                    node.library_error('library-error:'+json.dumps(changed),client,expected)
        opaque=payload('waki','body','stream failed','input_stream read failed: LastOperationFailed(Error { handle: 1 })')
        proof=node.library_error(opaque,'waki','error:response-size')
        self.assertFalse(proof['exactUnderlyingCategoryProven'])
        self.assertFalse(proof['nativeErrorInferredFromResourceHandle'])
        with self.assertRaises(Exception):node.library_error(opaque,'waki','error:timeout-option')
        real_body=payload('golem','body','request or response body error','real upstream Kind::Body source debug',
            isRequest=False,isBody=True,sourceDisplay='latent-http-response-too-large')
        self.assertTrue(node.library_error(real_body,'golem','error:response-size')['exactUnderlyingCategoryProven'])
        for substitute in ('latent-http-permission-denied','latent-http-unavailable','latent-runtime-resource-exhausted'):
            changed=json.loads(real_body.removeprefix('library-error:'))
            changed['public']['sourceDisplay']=substitute
            with self.subTest(substitute=substitute),self.assertRaises(Exception):
                node.library_error('library-error:'+json.dumps(changed),'golem','error:response-size')

    def test_actual_waki_header_error_requires_its_complete_exact_public_format(self):
        evidence=json.loads((qualification.ROOT/'docs/testing/evidence/rust-wasi-http-forbidden-reader-failure-2026-10-21.json').read_bytes())
        row=evidence['actualInvocation'];payload=row['decoded'][0]['ok'].removeprefix('fresh:waki:')
        actual=json.loads(payload.removeprefix('library-error:'))
        self.assertFalse(actual['debug']=='Forbidden') # exact failed original reader
        self.assertEqual(row['response']['data']['consumption']['outboundRequests'],0)
        self.assertTrue(row['processReaped'])
        self.assertTrue(node.library_error(payload,'waki','error:reserved-header')['exactUnderlyingCategoryProven'])
        for field,value in (('debug','Forbidden'),('display','Forbidden'),
                ('typedWasiErrorCode','HttpRequestDenied'),('phase','body'),('serdeJsonError',True)):
            changed=copy.deepcopy(actual)
            if field in ('typedWasiErrorCode','serdeJsonError'):changed['public'][field]=value
            else:
                changed[field]=value
                if field!='phase':changed[field+'Bytes']=len(value.encode())
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                node.library_error('library-error:'+json.dumps(changed),'waki','error:reserved-header')

    def test_source_authenticated_library_formatters_refuse_unprefixed_or_wrong_typed_variants(self):
        proof=json.loads((qualification.ROOT/'docs/testing/evidence/rust-wasi-http-library-formatter-source-2026-10-21.json').read_bytes())
        self.assertEqual((proof['compileExitCode'],proof['runExitCode']),(0,0))
        self.assertFalse(proof['guestOrNativeProductExecuted'])
        for client in ('waki','golem'):
            for code in proof['formatterStrings']:
                expected=('error:reserved-header' if code=='HeaderError::Forbidden' else
                    'error:request-denied' if code=='ErrorCode::HttpRequestDenied' else
                    'error:resource-capacity' if 'latent-runtime-resource-exhausted' in code else
                    'error:response-size' if 'latent-http-response-too-large' in code else
                    'error:uncertain-post' if 'latent-http-uncertain' in code else 'error:body-or-protocol')
                public=({'typedWasiErrorCode':None if code=='HeaderError::Forbidden' else code,
                    'serdeJsonError':False} if client=='waki' else {'isBuilder':False,'isRequest':True,
                    'isBody':False,'isDecode':False,'isTimeout':False,'isStatus':False,
                    'serdeJsonError':False,'sourceDisplay':code})
                value={'phase':'send','display':code,'debug':code,'displayBytes':len(code),
                    'debugBytes':len(code),'public':public,'truncated':False}
                self.assertTrue(node.library_error('library-error:'+json.dumps(value),client,expected)['exactUnderlyingCategoryProven'])
                changed=copy.deepcopy(value);short=code.split('::',1)[1]
                changed.update(display=short,debug=short,displayBytes=len(short),debugBytes=len(short))
                if client=='golem':changed['public']['sourceDisplay']=short
                elif public['typedWasiErrorCode'] is not None:changed['public']['typedWasiErrorCode']=short
                with self.subTest(client=client,code=code),self.assertRaises(RuntimeError):
                    node.library_error('library-error:'+json.dumps(changed),client,expected)

    def test_full52_case_aggregate_is_bounded_without_losing_original_per_case_values(self):
        record={'schemaVersion':'latent.rust.wasi-http.node.v1','status':'passed',
            'cases':[],'preEntryRefusals':[],'guestExecutions':53,'invocationAttempts':64}
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            for tenant,client in (('examples','waki'),('foreign','golem')):
                labels=[tenant+'-'+spec[0] for spec in node.cases()]+[tenant+'-cross-fresh']
                for label in labels:
                    item={'case':label,'tenant':tenant,'client':client,'observedContacts':1,
                        'invocation':{'controlledPublicEvidence':'x'*20000}}
                    record['cases'].append(item);node.write_json(output/('case-'+label+'.json'),item)
            self.assertGreater(len(json.dumps(record).encode()),262144)
            summary=node.compact_record(record,output)
            self.assertEqual((len(summary['cases']),summary['guestExecutions'],summary['invocationAttempts']),(52,53,64))
            node.write_json(output/'qualification.json',summary)
            self.assertLess((output/'qualification.json').stat().st_size,32768)
            for original,reference in zip(record['cases'],summary['cases']):
                path=output/reference['evidence']['path']
                self.assertEqual(json.loads(path.read_bytes()),original)
                self.assertEqual(node.file_identity(path,262144),{k:reference['evidence'][k] for k in ('sha256','bytes')})
            first=output/summary['cases'][0]['evidence']['path']
            first.write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'original-evidence-required'):
                node.compact_record(record,output)

    def test_failed_summary_collection_never_masks_the_primary_controller_failure(self):
        class PrimaryFailure(RuntimeError):pass
        with tempfile.TemporaryDirectory() as temporary:
            record={'schemaVersion':'latent.rust.wasi-http.node.v1','status':'failed','stage':'examples-reserved-auth'}
            with patch.object(node,'compact_record',side_effect=ValueError('injected summary refusal')):
                node.retain_failed_record(Path(temporary),record)
            fallback=json.loads((Path(temporary)/'FAILED.json').read_bytes())
            self.assertTrue(fallback['originalFailurePreserved'])
            self.assertTrue(fallback['summaryRetentionRefused'])
            self.assertFalse(fallback['qualification'])
            with patch.object(node,'compact_record',side_effect=ValueError('injected summary refusal')), \
                    patch.object(node,'write_json',side_effect=OSError('injected disk refusal')), \
                    self.assertRaisesRegex(PrimaryFailure,'original controller failure'):
                try:raise PrimaryFailure('original controller failure')
                except PrimaryFailure:
                    node.retain_failed_record(Path(temporary),record)
                    raise

    def row(self,action=''):
        code={'trap':'guest-trap','cancel':'cancelled','deadline':'deadline-exceeded'}.get(action)
        revision={'releaseDigest':'controlled-original'}
        data={'resolvedRevision':revision,'consumption':{'outboundRequests':1,'effectCount':0,
            'cpuFuel':'10','peakMemoryBytes':'65536'}}
        response={'outcomeKnown':True,'requestDispatched':True,'data':data}
        row={'processReaped':True,'exitCode':0,'decoded':[{'ok':'fresh:waki:'+node.DOMAIN_TEXT}], 'response':response}
        if code:
            data['terminalState']=code.replace('-','_')
            response.update(category='platform-failure',error={'code':code})
            row.update(exitCode=4,decoded=None)
        spec=('name','json','/conformance/json',None if code else node.DOMAIN_TEXT,1,'domain-json',action)
        return row,spec,revision,{'cpuFuel':100,'memoryBytes':1048576}

    def test_result_is_the_real_rust_result_type_with_exact_current_revision_and_budget(self):
        row,spec,revision,budget=self.row()
        node.outcome(row,spec,'waki',revision,budget)
        mutations=[lambda v:v.update(decoded=['fresh:waki:'+node.DOMAIN_TEXT]),
            lambda v:v.update(decoded=[{'err':'transport error'}]),lambda v:v.update(processReaped=False),
            lambda v:v.update(exitCode=False),
            lambda v:v['response']['data']['consumption'].update(cpuFuel=True),
            lambda v:v['response']['data']['consumption'].update(peakMemoryBytes=65536.5),
            lambda v:v['response'].update(outcomeKnown=False),
            lambda v:v['response']['data'].update(resolvedRevision={}),
            lambda v:v['response']['data']['consumption'].update(outboundRequests=2),
            lambda v:v['response']['data']['consumption'].update(cpuFuel='101'),
            lambda v:v['response']['data']['consumption'].update(peakMemoryBytes='1048577')]
        for mutate in mutations:
            changed=copy.deepcopy(row);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(Exception):node.outcome(changed,spec,'waki',revision,budget)

    def test_root_cancel_deadline_and_trap_never_accept_successful_library_completion(self):
        for action in ('trap','cancel','deadline'):
            row,spec,revision,budget=self.row(action)
            node.outcome(row,spec,'waki',revision,budget)
            for code in ('success','socket-timeout','unavailable','resource-exhausted'):
                changed=copy.deepcopy(row);changed['response']['error']['code']=code
                with self.subTest(action=action,code=code),self.assertRaises(Exception):
                    node.outcome(changed,spec,'waki',revision,budget)

    def test_pending_requires_all_five_original_physical_owners_and_current_tenant_provider_work(self):
        physical={'inventory':{'topology':{'available':True,'complete':True,
            'entries':[{'name':name,'activeCount':'1'} for name in node.PHYSICAL]}}}
        proof=json.loads((qualification.ROOT/'docs/testing/evidence/rust-wasi-http-tenant-counter-failure-2026-10-21.json').read_bytes())
        counts={'nodeUsage':proof['observedNodeUsage'], 'tenantUsage':proof['observedTenantUsage']}
        self.assertIsNot(counts['tenantUsage']['unavailable'],False) # actual old RED
        for name in ('broker_calls','pool_active_connections','pool_running_requests'):
            counts['nodeUsage']['counters'][name]='1'
        with patch.object(node,'sample',return_value=physical),patch.object(node,'usage',return_value=counts):
            self.assertIn('owners',node.positive_pending(None,None,None)['proof'])
            for mutate in ('unavailable','incomplete','duplicate'):
                changed=copy.deepcopy(physical);topology=changed['inventory']['topology']
                if mutate=='unavailable':topology['available']=False
                if mutate=='incomplete':topology['complete']=False
                if mutate=='duplicate':topology['entries'].append(topology['entries'][0])
                with self.subTest(mutate=mutate),patch.object(node,'sample',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)
            for name in node.PHYSICAL:
                changed=copy.deepcopy(physical)
                next(r for r in changed['inventory']['topology']['entries'] if r['name']==name)['activeCount']='0'
                with self.subTest(owner=name),patch.object(node,'sample',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)
            for key in ('calls','sessions'):
                changed=copy.deepcopy(counts);changed['tenantUsage']['counters'][key]='0'
                with self.subTest(owner=key),patch.object(node,'usage',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)
            for kind in ('scope','false','unknown','dict','missing','counter-missing','counter-type','boolean','negative','overflow'):
                changed=copy.deepcopy(counts);tenant=changed['tenantUsage']
                if kind=='scope':tenant['scope']='node'
                elif kind=='false':tenant['unavailable']=False
                elif kind=='unknown':tenant['unavailable']=['provider-unavailable']
                elif kind=='dict':tenant['unavailable']={}
                elif kind=='missing':tenant.pop('unavailable')
                elif kind=='counter-missing':tenant['counters'].pop('calls')
                elif kind=='counter-type':tenant['counters']=[]
                elif kind=='boolean':tenant['counters']['calls']=True
                elif kind=='negative':tenant['counters']['sessions']='-1'
                else:tenant['counters']['calls']=str(2**64)
                with self.subTest(tenant=kind),patch.object(node,'usage',return_value=changed),self.assertRaises(Exception):
                    node.positive_pending(None,None,None)

    def test_programme_remains_within_original_peer_and_per_activation_authority_limits(self):
        rows=node.cases()
        self.assertEqual(len(rows),25)
        self.assertEqual(len({r[0] for r in rows}),25)
        self.assertEqual(sum(r[4] for r in rows)+1+1,31) # original max32: queue holder and final fresh
        self.assertTrue(all(0<=r[4]<=8 for r in rows))
        for label in ('reserved-auth','reserved-cookie','foreign-target','timeout-option-unsupported'):
            row,=[r for r in rows if r[0]==label]
            self.assertEqual(row[4],0)
        for label,action in (('pending-cancel','cancel'),('pending-deadline','deadline'),('root-trap','trap')):
            self.assertEqual(next(r for r in rows if r[0]==label)[6],action)
        self.assertEqual(next(r for r in rows if r[0]=='uncertain-post')[4:6],(1,'commit-close'))

    def test_capacity_uses_actual_accepted_count_and_specific_error_without_naming_an_unobserved_owner(self):
        for client in ('waki','golem'):
            row,_spec,revision,budget=self.row()
            spec=next(r for r in node.cases() if r[0]=='resource-capacity')
            code='ErrorCode::InternalError(Some("latent-runtime-resource-exhausted"))'
            public=({'typedWasiErrorCode':code,'serdeJsonError':False} if client=='waki' else {
                'isBuilder':False,'isRequest':True,'isBody':False,'isDecode':False,'isTimeout':False,
                'isStatus':False,'serdeJsonError':False,'sourceDisplay':code})
            error={'phase':'send','display':code,'debug':code,'displayBytes':len(code),'debugBytes':len(code),
                'truncated':False,'public':public}
            for accepted in (1,5,8):
                row['decoded']=[{'ok':f'fresh:{client}:capacity:{accepted}:library-error:'+json.dumps(error)}]
                row['response']['data']['consumption']['outboundRequests']=accepted
                proof=node.outcome(row,spec,client,revision,budget)
                self.assertEqual(proof['observedAcceptedResponses'],accepted)
                self.assertFalse(proof['limitingOwnerKindProven'])
                self.assertFalse(proof['taskExhaustionClaimed'])
            for mutate in ('zero','ninth','count','unavailable','permission','unsupported'):
                changed=copy.deepcopy(row);value=copy.deepcopy(error)
                if mutate in {'zero','ninth'}:
                    changed['decoded']=[{'ok':f'fresh:{client}:capacity:{0 if mutate=="zero" else 9}:library-error:'+json.dumps(value)}]
                elif mutate=='count':changed['response']['data']['consumption']['outboundRequests']=7
                else:
                    value['public']['typedWasiErrorCode' if client=='waki' else 'sourceDisplay']=mutate
                    changed['decoded']=[{'ok':f'fresh:{client}:capacity:8:library-error:'+json.dumps(value)}]
                with self.subTest(client=client,mutate=mutate),self.assertRaises(Exception):
                    node.outcome(changed,spec,client,revision,budget)

    def test_golem_transitive_timer_uses_original_closed_pending_not_preparation_or_elapsed_time(self):
        prefix=node.TIMER_PREFIX
        def record(event=b'wait-pending',counts=b'1|2|1',sequence=b'1',mode=b'pending'):
            return prefix+b'|'+mode+b'|'+event+b'|'+sequence+b'|'+counts+b'\n'
        proof=node.golem_timer_pending(record(),'pending')
        self.assertEqual(proof['waitPending']['tasks'],1)
        self.assertFalse(proof['nativeHookChanged'])
        self.assertFalse(proof['otherLanguageExecutionClaimed'])
        self.assertEqual(proof['originalReader'],'tools/dotnet_resource_timer_observer.py')
        for raw in (b'',record(b'start-accepted'),record(b'next-entered'),record()[:-1],
            record(counts=b'0|2|1'),record(counts=b'1|0|1'),record(counts=b'1|2|0')):
            self.assertIsNone(node.golem_timer_pending(raw,'pending'))
        for raw in (record(counts=b'9|2|1'),record(counts=b'1|17|1'),record(counts=b'1|2|9'),
            prefix+b'|overflow\n',record(sequence=b'2'),record()+record(),
            record()+record(b'root-close',sequence=b'2')):
            with self.subTest(raw=raw),self.assertRaises(Exception):node.golem_timer_pending(raw,'pending')
        self.assertIsNone(node.golem_timer_pending(record(mode=b'drain'),'pending'))

    def test_two_tenant_configuration_binds_only_three_exact_authorities_and_policy_ids(self):
        values={'workers':{'runtime':1,'control':1},'cells':[{'capacity':1,'queueCapacity':2}],
            'credentials':[{'tenant':'examples'}],'providers':{'formatVersion':1,'bindings':[],
                'httpStreaming':{'identity':{'id':'http-standard','tenant':'examples','service':'http-host','epoch':1},
                    'configuration':{'destinations':[]},'credentialDirectory':'unchanged',
                    'credentials':[{'file':'unchanged'}]},
                'activationRuntime':{'identity':{'id':'activation','tenant':'examples','service':'activation-host','epoch':1},
                    'limits':dict(node.RUNTIME_LIMITS)}}}
        for name,capability in (('clockMonotonic',node.CLOCK),('clockWall','unused-wall'),('random','unused-random')):
            values['providers'][name]={'identity':{'id':name,'tenant':'examples','service':'runtime-host','epoch':1}}
        for name,capability in (('http-standard',node.HTTP),('activation',node.ACTIVATION),
            ('clockMonotonic',node.CLOCK),('clockWall','unused-wall'),('random','unused-random')):
            values['providers']['bindings'].append({'name':name,'tenant':'examples','consumerService':'old',
                'providerService':('http-host' if name=='http-standard' else 'activation-host' if name=='activation' else 'runtime-host'),
                'contract':capability,'providerBinding':name+'-old'})
        peers={tenant:Mock() for tenant in node.TENANTS}
        for peer in peers.values():peer.provider_destinations.return_value=[{'controlled':'origin'}]
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            credentials={t:root/t/'authorization' for t in node.TENANTS}
            path=root/'config.json'
            for http_present in (True,False):
                path.write_bytes(canonical(values))
                with patch.object(node.shared,'configuration',return_value=path):
                    self.assertEqual(node.configuration(root,root,peers,credentials,http_present=http_present),path)
                import json
                actual=json.loads(path.read_bytes())['providers']
                expected={node.CLOCK,node.ACTIVATION}|({node.HTTP} if http_present else set())
                self.assertEqual({r['contract'] for r in actual['bindings']},expected)
                self.assertEqual(len(actual['bindings']),2*len(expected))
                self.assertEqual(actual['activationRuntime']['limits'],node.RUNTIME_LIMITS)
                self.assertEqual(len(actual['scalarAliases']),2)
                names={node.HTTP:'http-standard',node.CLOCK:'clockMonotonic',node.ACTIVATION:'activation'}
                for row in actual['bindings']:
                    self.assertEqual(row['consumerService'],node.SERVICE)
                    self.assertEqual(row['providerBinding'],names[row['contract']]+'-'+row['tenant']+'-installed')
                self.assertNotIn('clockWall',actual);self.assertNotIn('random',actual)
                self.assertEqual('httpStreaming' in actual,http_present)

    def test_neutral_deployment_never_changes_world_or_inherits_foreign_grants(self):
        original={'metadata':{'name':'unchanged'},'spec':{'service':node.SERVICE,'grants':[]}}
        result=node.deployment(original,'foreign')
        self.assertEqual(result['metadata'],{'name':'rust-http-foreign','tenant':'foreign'})
        self.assertEqual(result['spec'],original['spec'])
        self.assertEqual(original['metadata'],{'name':'unchanged'})
        for mutate in ({'tenant':None},{'tenant':'examples'}):
            value=copy.deepcopy(original);value['metadata'].update(mutate)
            with self.assertRaises(Exception):node.deployment(value,'foreign')


if __name__=='__main__':unittest.main()

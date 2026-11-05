import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import admit_dotnet_neutral_evidence as admission
from tools import compile_dotnet_neutral_verify as compiler
from tools import dotnet_frozen_polly_inputs as inputs
from tools import dotnet_neutral_stack as neutral
from tools import guest_emitted_code as emitted


class FrozenPollyInputsTests(unittest.TestCase):
    def metadata(self):
        return (
            {'id':inputs.RUN, 'event':'pull_request', 'head_sha':inputs.HEAD,
             'status':'completed', 'conclusion':'success',
             'repository':{'id':inputs.REPOSITORY_ID}, 'head_repository':{'id':inputs.REPOSITORY_ID}},
            {'id':inputs.JOB, 'run_id':inputs.RUN, 'head_sha':inputs.HEAD,
             'status':'completed', 'conclusion':'success',
             'name':'Published Polly default retry and timer factories'},
            {'id':inputs.ARTIFACT, 'name':inputs.ARTIFACT_NAME, 'size_in_bytes':inputs.ARCHIVE_BYTES,
             'expired':False, 'digest':'sha256:' + inputs.ARCHIVE_HASH,
             'workflow_run':{'id':inputs.RUN, 'head_sha':inputs.HEAD,
                 'repository_id':inputs.REPOSITORY_ID, 'head_repository_id':inputs.REPOSITORY_ID}})

    def test_exact_origin_and_reject_changed_producer_or_expiry(self):
        rows=self.metadata()
        inputs.verify_metadata(*rows)
        for index, key, value in ((0,'head_sha','0'*40), (1,'conclusion','failure'),
                                  (2,'expired',True), (2,'digest','sha256:'+'0'*64)):
            changed=copy.deepcopy(rows)
            changed[index][key]=value
            with self.assertRaises(ValueError):
                inputs.verify_metadata(*changed)

    def test_unknown_archive_refuses_before_extraction(self):
        with self.assertRaisesRegex(ValueError,'archive-identity'):
            inputs.unpack(b'PK\x03\x04',None)


class NeutralStackTests(unittest.TestCase):
    def test_stack_get_and_set_roundtrip(self):
        body=b'\x00\x23'+neutral.ZERO5+b'\x24'+neutral.ZERO5+b'\x0b'
        changed,gets,sets=neutral.rewrite_body(body,emitted.Budget(),10719,False)
        self.assertEqual((gets,sets),(1,1))
        self.assertEqual(neutral.rewrite_body(changed,emitted.Budget(),10719,True),(body,1,1))
        self.assertNotEqual(body,changed)

    def test_wrong_identity_and_truncation_refused(self):
        for data in (b'',b'\0asm',bytes(neutral.ORIGINAL_BYTES)):
            with self.assertRaisesRegex(ValueError,'original-component-identity'):
                neutral.produce(data)

    def test_future_calls_and_non_padded_global_refused(self):
        with self.assertRaisesRegex(ValueError,'nonpadded-stack-global'):
            neutral.rewrite_body(b'\x00\x23\x00\x0b',emitted.Budget(),10719,False)
        with self.assertRaisesRegex(ValueError,'future-function-reference'):
            neutral.rewrite_body(b'\x00\x10'+neutral.padded5(10719)+b'\x0b',
                                 emitted.Budget(),10719,False)

    def test_instruction_limit_is_restored_on_failure(self):
        previous=emitted.MAX_INSTRUCTIONS
        with self.assertRaises(ValueError):
            neutral.derive(b'not a module')
        self.assertEqual(previous,emitted.MAX_INSTRUCTIONS)

    def test_component_depth_and_integer_bounds(self):
        with self.assertRaisesRegex(ValueError,'component-depth'):
            neutral.replace_component(neutral.COMP,b'',b'',4)
        for value in (-1,2**32):
            with self.assertRaisesRegex(ValueError,'u32'):
                neutral.padded5(value)


class CompilerSelectionTests(unittest.TestCase):
    def test_exact_locked_artifacts_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            deps=root/'deps'
            deps.mkdir()
            parser=deps/'libwasmparser-abcdef.rlib'
            sha=deps/'libsha2-abcdef.rlib'
            parser.write_bytes(b'parser')
            sha.write_bytes(b'sha')
            messages=root/'cargo.jsonl'
            rows=[{'reason':'compiler-artifact','package_id':'registry+test#wasmparser@0.259.0',
                   'filenames':[str(parser)]},
                  {'reason':'compiler-artifact','package_id':'registry+test#sha2@0.11.0',
                   'filenames':[str(sha)]}]
            def write():
                messages.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
            write()
            self.assertEqual(compiler.select_artifacts(messages,deps),
                             {'wasmparser@0.259.0':parser.resolve(),'sha2@0.11.0':sha.resolve()})
            other=deps/'libwasmparser-fedcba.rlib'
            other.write_bytes(b'other')
            rows.append({'reason':'compiler-artifact','package_id':'registry+test#wasmparser@0.259.0',
                         'filenames':[str(other)]})
            write()
            with self.assertRaisesRegex(ValueError,'artifact-ambiguity'):
                compiler.select_artifacts(messages,deps)


class EvidenceAdmissionTests(unittest.TestCase):
    def test_only_allowlisted_evidence_is_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'observed').mkdir()
            (root/'observed'/'checkout.txt').write_text('source',encoding='utf-8')
            (root/'observed'/'private-token.txt').write_text('never-copy',encoding='utf-8')
            result=admission.admit(root)
            self.assertEqual(set(result['files']),{'checkout.txt'})
            self.assertFalse((root/'public'/'private-token.txt').exists())

    def test_oversized_log_and_wrong_binary_are_refused(self):
        for name,data in (('cargo.log',bytes(1024*1024+1)),('original.wasm',b'forged')):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                (root/'observed').mkdir()
                (root/'observed'/name).write_bytes(data)
                with self.assertRaises(ValueError):
                    admission.admit(root)
                self.assertFalse((root/'public').exists())



if __name__=='__main__':
    unittest.main()
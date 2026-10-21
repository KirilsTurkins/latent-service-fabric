"""The finite CoreLib helper composes with exact closed-filesystem preservation."""
import copy
import unittest
from tools.dotnet_guest import closed_filesystem as filesystem, task_wait
from tools.rust_capsule_project import digest, write_json
from tools.tests import test_dotnet_closed_filesystem as controls
from tools.tests.test_dotnet_finite_task_wait import FINITE, DECLARATIONS


class FiniteFilesystemComposition(unittest.TestCase):
    def control(self):
        outer=controls.ClosedFilesystemPortTests();outer.setUp();self.addCleanup(outer.doCleanups)
        f=outer.fixture;f.declared=DECLARATIONS
        def rewrite(stage,*args):
            self.assertEqual(args[2],'--finite-task-wait')
            args[-2].write_bytes(b'finite-control')
            write_json(args[-1],{**f.receipt,**FINITE,'outputDigest':digest(b'finite-control')})
        f.run_tool=rewrite
        port=f.prepare()
        return outer,port

    def test_finite_chain_accepts_exact_tenth_helper_and_preserves_final_native_reference(self):
        outer,intermediate=self.control();f=outer.fixture
        def rewrite(stage,*args):
            self.assertEqual(stage,'closed-filesystem-rewrite')
            original,base,assembly,receipt=args[-4:]
            assembly.write_bytes(base.read_bytes()+b'-closed')
            write_json(receipt,{**outer.receipt,'baseDigest':intermediate.identity['digest'],
                'outputDigest':digest(assembly.read_bytes()),'unchangedBaseMethods':44754})
        selected=filesystem.prepare(f.sdk,f.tools,f.packages,f.root/'dotnet',f.project,f.output,f.evidence,
            rewrite,task_wait_port=intermediate)
        outer.references(selected,intermediate)
        result=intermediate.finish(f.project,f.evidence,corelib_port=selected)
        self.assertEqual(intermediate.validated_helper_count(),10)
        self.assertEqual(selected.evidence['unchangedBaseMethods'],44754)
        self.assertEqual(result['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'],selected.identity['digest'])

    def test_exact_counts_keep_unjoined_and_infinite_modes_and_refuse_arbitrary_count_or_port(self):
        outer,port=self.control()
        pure=outer.receipt;filesystem.validate_receipt(pure,task_wait.SOURCE,False)
        infinite={**pure,'baseDigest':port.identity['digest'],'unchangedBaseMethods':44753}
        filesystem.validate_receipt(infinite,port.identity['digest'],True)
        finite={**infinite,'unchangedBaseMethods':44754}
        filesystem.validate_receipt(finite,port.identity['digest'],True,task_wait_port=port)
        for value in (44753,44755,True):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'rewrite-receipt'):
                filesystem.validate_receipt({**finite,'unchangedBaseMethods':value},port.identity['digest'],True,task_wait_port=port)
        for joined,selected in ((1,None),(False,port),(True,object())):
            with self.subTest(joined=joined),self.assertRaises(ValueError):
                filesystem.validate_receipt(finite,port.identity['digest'],joined,task_wait_port=selected)

    def test_helper_count_requires_validated_mode_receipt_bytes_and_explicit_declarations(self):
        _outer,port=self.control();original=copy.deepcopy(port.evidence)
        changes=(('generatedHelperCount',9),('generatedHelperCount',True),
            ('finiteAndCancellableWaits','unknown'),('waitCancellation','replacement-token'),('outputDigest',digest(b'foreign')))
        for key,value in changes:
            port.evidence=copy.deepcopy(original);port.evidence[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):port.validated_helper_count()
        port.evidence=copy.deepcopy(original);port.evidence['selection']['requiredDeclarations'].pop()
        with self.assertRaisesRegex(ValueError,'authenticated-helper-count'):port.validated_helper_count()
        port.evidence=original
        saved=port.assembly.read_bytes();port.assembly.write_bytes(b'changed-backing-assembly')
        with self.assertRaisesRegex(ValueError,'derived-CoreLib-changed'):port.validated_helper_count()
        port.assembly.write_bytes(saved)


if __name__=='__main__':unittest.main()

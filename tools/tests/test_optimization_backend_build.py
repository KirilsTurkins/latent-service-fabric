"""Build-only ownership/control regressions without Git or compiler execution."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import build_optimization_backend_revision as cli
from tools.optimization_backend_revision import build
from tools.optimization_revision_runner import backend


REFS={"control":"a"*40,"candidate":"b"*40,"harness":"c"*40}


class BackendBuildTests(unittest.TestCase):
    def test_default_build_parent_is_owned_external_and_removed(self):
        seen=[]
        def execute(args,repo):
            seen.append(args.target_root)
            self.assertTrue(args.target_root.is_dir())
            self.assertFalse(args.target_root.is_relative_to(repo))
            return 0
        with patch.object(cli,"execute",side_effect=execute):
            self.assertEqual(cli.main(["--control-ref",REFS["control"],"--candidate-ref",REFS["candidate"],
                                       "--harness-ref",REFS["harness"],"--experiment","cold","--output","unused"]),0)
        self.assertFalse(seen[0].exists())

    def test_cpu_source_is_required_only_for_cold_experiment(self):
        def git(_repo,*args):
            return "different" if args[-1] == REFS["candidate"]+":"+backend.COLD_CONTROLS[0] else "same"
        with patch.object(build.shared,"git",side_effect=git):
            build.matching_controls(Path("unused"),REFS,"warm")
            with self.assertRaisesRegex(ValueError,"source-controls-differ"):
                build.matching_controls(Path("unused"),REFS,"cold")

    def test_non_sha_and_dirty_harness_fail_before_owned_build(self):
        args=SimpleNamespace(profile="full",experiment="cold",control_ref="development",
                             candidate_ref=REFS["candidate"],harness_ref=REFS["harness"])
        with patch.object(build.platform,"system",return_value="Linux"), patch.object(build,"collect") as work:
            with self.assertRaisesRegex(ValueError,"full-commit"):
                build.execute(args,Path("unused"))
            args.control_ref=REFS["control"]
            with patch.object(build.shared,"source",return_value={"commit":REFS["harness"],"clean":False}):
                with self.assertRaisesRegex(ValueError,"clean-harness-ref"):
                    build.execute(args,Path("unused"))
            work.assert_not_called()

    def run_builds(self,failure=False):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary)
            output,target=parent/"evidence",parent/"external"
            output.mkdir()
            target.mkdir()
            receipt={"builds":{},"harness":None,"cleanup":{"owned_worktree_removed":False}}
            current=[REFS["control"]]
            git_calls,build_calls=[],[]
            def git(_repo,*args):
                git_calls.append(args)
                if args[:2] == ("worktree","add"):
                    Path(args[3]).mkdir()
                elif args[:2] == ("worktree","remove"):
                    Path(args[3]).rmdir()
                elif args[:2] == ("checkout","--detach"):
                    current[0]=args[2]
                return ""
            def compiled(root,build_target,label,out,deadline):
                build_calls.append((root,build_target,label))
                if failure:
                    raise RuntimeError("injected-build-failure")
                return {"source":{"commit":current[0]},"executables":{"backend":label}}
            def echo(root,build_target,out,deadline):
                build_calls.append((root,build_target,"harness"))
                return {"source":{"commit":current[0]},"echo":{"component":"retained"}}
            with patch.object(build.shared,"git",side_effect=git), \
                    patch.object(build.shared,"source",side_effect=lambda _: {"commit":current[0],"clean":True}), \
                    patch.object(build.backend,"build_backend",side_effect=compiled), \
                    patch.object(build.backend,"build_echo",side_effect=echo), \
                    patch.object(build.shared,"build_one") as external:
                if failure:
                    with self.assertRaisesRegex(RuntimeError,"injected-build-failure"):
                        build.collect(parent,REFS,output,target,2**63,receipt)
                else:
                    build.collect(parent,REFS,output,target,2**63,receipt)
                external.assert_not_called()
            self.assertTrue(receipt["cleanup"]["owned_worktree_removed"])
            self.assertEqual(list(target.iterdir()),[])
            self.assertTrue(any(args[:2] == ("worktree","remove") for args in git_calls))
            self.assertTrue((output/"backend-builds.json").is_file())
            return receipt,build_calls

    def test_only_two_collectors_and_one_echo_share_exact_owned_paths(self):
        receipt,calls=self.run_builds()
        self.assertEqual([row[2] for row in calls],["control","candidate","harness"])
        self.assertEqual(len({(row[0],row[1]) for row in calls}),1)
        self.assertEqual(set(receipt["builds"]),{"control","candidate"})

    def test_failed_build_removes_worktree_without_claiming_completed_inputs(self):
        receipt,calls=self.run_builds(failure=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(receipt["builds"],{})
        self.assertIsNone(receipt["harness"])


if __name__ == "__main__":
    unittest.main()

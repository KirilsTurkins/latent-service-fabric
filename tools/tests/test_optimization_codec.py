"""Bounded model/projection regressions; synthetic unit rows are not release evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_codec import aggregate, allocations, builds, evidence, events, model
from tools.optimization_codec.fixtures import fixtures
from tools.optimization_codec.parse import parse
from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_evidence.common import canonical, sha256
from tools.artifact_identity_runner.files import reference
from tools.optimization_revision_runner import backend, codec, ownership
from tools.optimization_runner.plans import cases
from tools import validate_phase1_archive as archive

ROOT = Path(__file__).resolve().parents[2]


class Models(unittest.TestCase):
    def test_exact_fixed_populations_and_resolved_family_work(self):
        expected = [(131,123,13,4096),(14627,14627,1,573),(2850,2850,6,2943),
                    (65540,65540,1,127),(122884,122884,1,68),(98308,49156,1,85)]
        for family, fixed in zip(model.FAMILIES, expected, strict=True):
            source, output, arity = fixtures()[family]
            self.assertEqual((len(source),len(output),arity,model.plan("full",family=family)["measured_iterations"]),fixed)
            self.assertEqual(len(json.loads(source)),arity)
            self.assertEqual(len(json.loads(output)),arity)
        for profile, children, calls, external in (("smoke",24,432,140),("full",168,449680,25256)):
            cells=list(model.population(profile));self.assertEqual(len(cells),children)
            self.assertEqual(sum(6+2*(model.plan(profile,*cell)["warmup_iterations"]+model.plan(profile,*cell)["measured_iterations"]) for cell in cells),calls)
            chosen=codec.plan(profile);originals={row["id"]:row for row in cases(profile)}
            self.assertEqual(chosen["cases"],[originals[key] for key in codec.CASE_IDS])
            self.assertEqual(chosen["setup_cases"],[])
            self.assertEqual(2*chosen["repetitions"]*sum(row["client_plan"]["warmup_attempts"]+row["client_plan"]["measured_attempts"] for row in chosen["cases"]),external)
        self.assertEqual(ownership.CASE_IDS,("warm-echo","payload-64k","payload-near-limit"))
        self.assertEqual(backend.libtest_recipe("codec"),backend.libtest_recipe("lookup"))
        self.assertIn("latent-wasmtime-codec",backend.LIBTESTS["codec"])

    def test_closed_plan_rejects_adaptive_or_boolean_population(self):
        for change in ({"repetition":True},{"repetition":8},{"mode":"adaptive"},{"family":"other"},{"variant":"legacy"}):
            with self.assertRaises(ValueError):model.plan("full",**change)

    def test_all_schema_plans_and_declared_caps(self):
        import jsonschema
        for kind, values in (("codec",[model.plan(profile,*cell) for profile in ("smoke","full") for cell in model.population(profile)]),
                             ("codec-rpc",[codec.plan(profile) for profile in ("smoke","full")])):
            schema=json.loads((ROOT/f"benchmarks/optimization/{kind}-plan.schema.json").read_bytes())
            validator=jsonschema.Draft202012Validator(schema)
            for value in values:validator.validate(value)
            changed=copy.deepcopy(values[0]);changed["profile"]="adaptive"
            with self.assertRaises(jsonschema.ValidationError):validator.validate(changed)
        for profile in ("smoke","full"):
            suite=dict.fromkeys("builds runner_source runner_source_after status reason elapsed_nanos tools symbols runs artifacts".split())
            suite.update(schema=model.SCHEMA,profile=profile,plan=model.suite_plan(profile))
            suite["plan"]["maximum_folded_expanded_bytes"]=str(64*1024**2)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/"suite.json";path.write_bytes(canonical(suite))
                with self.assertRaisesRegex(ValueError,"codec-suite-schema-or-plan"):evidence.validate_suite(path)

    def test_common_controls_exclude_the_production_switch(self):
        self.assertFalse(any(name.endswith("/values.rs") or "/values/typed" in name or name.endswith("/tests.rs") for name in builds.COMMON))
        self.assertIn(model.TYPE_FIXTURE,builds.COMMON)
        self.assertIn("crates/latent-wasmtime/src/values/types.wat",builds.COMMON)
        self.assertIn("Cargo.lock",builds.COMMON)


class ClosedPlanSchemas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jsonschema
        cls.validation_error = jsonschema.ValidationError
        cls.validators = {}
        for name in ("codec-plan", "codec-rpc-plan", "codec-rpc-suite"):
            encoded = (ROOT / f"benchmarks/optimization/{name}.schema.json").read_bytes()
            if len(encoded) > 32 * 1024:
                raise AssertionError("fixed plans must use shared bounded definitions")
            schema = json.loads(encoded)
            jsonschema.Draft202012Validator.check_schema(schema)
            cls.validators[name] = jsonschema.Draft202012Validator(schema)

    def rejects(self, schema, original, mutate):
        changed = copy.deepcopy(original)
        mutate(changed)
        with self.assertRaises(self.validation_error):
            self.validators[schema].validate(changed)

    def test_every_generated_direct_plan_and_closed_population_conditions(self):
        validator = self.validators["codec-plan"]
        for profile in ("smoke", "full"):
            for cell in model.population(profile):
                value = model.plan(profile, *cell)
                with self.subTest(profile=profile, cell=cell):
                    validator.validate(value)
                    for key, changed in (("adaptive", True), ("profile", "other"),
                                         ("repetition", True), ("repetition", 0),
                                         ("repetition", 2 if profile == "smoke" else 8),
                                         ("family", "other"), ("mode", "other"),
                                         ("variant", "other"),
                                         ("warmup_iterations", value["warmup_iterations"] + 1),
                                         ("measured_iterations", value["measured_iterations"] + 1)):
                        self.rejects("codec-plan", value, lambda row, k=key, v=changed: row.__setitem__(k, v))
        value = model.plan("full", family="scalar-params")
        self.rejects("codec-plan", value, lambda row: row.__setitem__("family", "byte-list"))
        self.rejects("codec-plan", value, lambda row: row.pop("family"))

    def test_rpc_profiles_keep_exact_order_payloads_counts_and_nested_fields(self):
        for profile in ("smoke", "full"):
            value = codec.plan(profile)
            self.validators["codec-rpc-plan"].validate(value)
            for key, changed in (("adaptive", True), ("profile", "other"),
                                 ("repetitions", True), ("repetitions", 7 if profile == "smoke" else 1)):
                self.rejects("codec-rpc-plan", value, lambda row, k=key, v=changed: row.__setitem__(k, v))
            self.rejects("codec-rpc-plan", value, lambda row: row["cases"].reverse())
            self.rejects("codec-rpc-plan", value, lambda row: row["cases"].pop())
            self.rejects("codec-rpc-plan", value, lambda row: row["cases"].append(row["cases"][0]))
            for index in range(5):
                for key in ("warmup_attempts", "measured_attempts", "batch_size", "budget_millis"):
                    self.rejects("codec-rpc-plan", value, lambda row, i=index, k=key:
                                 row["cases"][i]["client_plan"].__setitem__(k, value["cases"][i]["client_plan"][k] + 1))
                self.rejects("codec-rpc-plan", value, lambda row, i=index:
                             row["cases"][i]["client_plan"].__setitem__("extra", None))
                self.rejects("codec-rpc-plan", value, lambda row, i=index:
                             row["cases"][i].__setitem__("id", "unknown"))
            # Equal-length payload tampering must still fail structural checking;
            # large repeated text is represented without embedding 120 KiB literals.
            for index in (3, 4):
                for suffix in ("y", "\n", "xx"):
                    self.rejects("codec-rpc-plan", value, lambda row, i=index, tail=suffix:
                                 row["cases"][i]["client_plan"]["payload"].__setitem__(0,
                                     value["cases"][i]["client_plan"]["payload"][0][:-1] + tail))
            self.rejects("codec-rpc-plan", value, lambda row:
                         row["cases"][2]["client_plan"]["payload"][0]["bytes"].__setitem__(1023, 0))
            self.rejects("codec-rpc-plan", value, lambda row:
                         row["cases"][2]["client_plan"]["payload"][0]["values"].__setitem__(63, 0))

    def test_suite_embeds_same_closed_plan_and_preserves_failed_receipts(self):
        for profile in ("smoke", "full"):
            suite = {"schema": codec.SCHEMA, "profile": profile, "plan": codec.plan(profile),
                     "requested_refs": {key: "a" * 40 for key in ("control", "candidate", "harness")},
                     "status": "failed", "reason": "collection-failed", "elapsed_nanos": "0",
                     "measurement_elapsed_nanos": "0", "identity": {}, "cleanup": {},
                     "runs": [], "artifacts": [], "builds": None, "clock_ticks_per_second": 100}
            self.validators["codec-rpc-suite"].validate(suite)
            for key, changed in (("extra", 1), ("profile", "other"), ("status", "complete")):
                self.rejects("codec-rpc-suite", suite, lambda row, k=key, v=changed: row.__setitem__(k, v))
            self.rejects("codec-rpc-suite", suite, lambda row:
                         row["plan"]["cases"][0]["client_plan"].__setitem__("measured_attempts", 1))
            self.rejects("codec-rpc-suite", suite, lambda row: row["plan"].__setitem__("unknown", 1))
            self.rejects("codec-rpc-suite", suite, lambda row: row.update(status="passed", reason=None))


class Fixture:
    def __init__(self, root, variant="control"):
        self.root=root;self.selected=model.plan("smoke",variant=variant)
        self.identity={"unit_fixture_only":True}
        self.task={"process_id":123,"thread_id":124,"start_time_ticks":125}
        source,output,arity=fixtures()[self.selected["family"]]
        for name,data in (("input.json",source),("expected-output.json",output),("plan.json",canonical(self.selected)),("identity.json",canonical(self.identity))):
            (root/name).write_bytes(data)
        self.record={"plan":reference(root/"plan.json",root),"identity":reference(root/"identity.json",root),"probe_process":{"process_id":123}}
        common={"process_id":123,"plan_sha256":self.record["plan"]["sha256"],"identity_sha256":self.record["identity"]["sha256"],
                **{key:self.selected[key] for key in ("family","mode","repetition","variant","observation_hold_millis")},"thread_identity":self.task}
        self.ready={"schema":"latent.optimization.codec-ready.v1","event":"ready",**common,"elapsed_nanos":"1000"}
        self.complete={"schema":"latent.optimization.codec-complete.v1","event":"measurement-complete",**common,"elapsed_nanos":"200000000","outcome":"passed"}
        self.type_fixture=reference(ROOT/model.TYPE_FIXTURE,ROOT)
        self.raw={"schema":"latent.optimization.codec-arm.v1","plan":self.selected,"identity":self.identity,
                  "process_id":123,"thread_identity":self.task,"plan_sha256":common["plan_sha256"],"identity_sha256":common["identity_sha256"],
                  "input":reference(root/"input.json",root),"expected_output":reference(root/"expected-output.json",root),
                  "type_fixture":{key:self.type_fixture[key] for key in ("sha256","bytes")},"limits":{k:str(v) for k,v in model.LIMITS.items()},
                  "preflight":{"started_nanos":"1","finished_nanos":"999","decode_path":"legacy-only" if variant=="control" else "typed-success",
                               "legacy_equivalent":True,"canonical_output_matches":True,"decoded_arity":str(arity),"encoded_bytes":str(len(output)),"decode_calls":"3","encode_calls":"3"},
                  "directions":[],"types_dropped":True,"guest_stores":"0","invokes":"0","elapsed_nanos":"199999999","outcome":"passed"}
        for i,(direction,expected) in enumerate((("decode",arity),("encode",len(output)))):
            row={"direction":direction,**{phase+"_"+key:str(count) for phase,count in (("warmup",2),("measured",4)) for key in ("attempted","completed","successes")},
                 "started_nanos":str(100002000+i*10000),"finished_nanos":str(100003000+i*10000),"elapsed_nanos":"1000",
                 "cpu":{"clock":"CLOCK_THREAD_CPUTIME_ID","resolution_nanos":"1","before_nanos":str(100+i*100),"after_nanos":str(150+i*100)},
                 "coarse_thread_cpu":{position:{"identity":self.task,"user_ticks":10+i,"system_ticks":1} for position in ("before","after")},
                 "observed_arity_or_bytes":str(expected*4),"failure":None}
            self.raw["directions"].append(row)

    def replay(self):
        (self.root/"codec.json").write_bytes(canonical(self.raw));self.record["raw"]=reference(self.root/"codec.json",self.root)
        self.complete["raw"]=self.record["raw"]
        for key,value in (("ready",self.ready),("result",self.complete)):
            (self.root/(key+".json")).write_bytes(canonical(value));self.record[key]=reference(self.root/(key+".json"),self.root)
        (self.root/"probe.log").write_bytes(canonical(self.ready)+b"\n"+canonical(self.complete)+b"\n")
        self.record.update(log=reference(self.root/"probe.log",self.root),started_micros="0",finished_micros="400000")
        artifacts=Artifacts(self.root,inventory(self.root));ready,complete=events.parse(self.record,self.selected,artifacts)
        return parse(self.raw,self.selected,self.identity,self.record,artifacts,self.type_fixture,ready,complete)


class SemanticProjection(unittest.TestCase):
    def test_both_projection_variants_and_all_operations(self):
        for variant in ("control","candidate"):
            with tempfile.TemporaryDirectory() as directory:
                result=Fixture(Path(directory),variant).replay()
                self.assertEqual(result["validated_codec_operations"],"18")
                self.assertEqual(result["validated_measured_operations"],"8")

    def mutate(self, change):
        with tempfile.TemporaryDirectory() as directory:
            fixture=Fixture(Path(directory),"candidate");change(fixture)
            with self.assertRaises(ValueError):fixture.replay()

    def test_rehashed_lineage_and_preflight_erasure_reject(self):
        for key,value in (("decode_path","legacy-only"),("legacy_equivalent",False),("canonical_output_matches",False),("decode_calls","2"),("encoded_bytes","122")):
            with self.subTest(key=key):self.mutate(lambda f:f.raw["preflight"].__setitem__(key,value))

    def test_rehashed_input_or_expected_bytes_reject(self):
        def changed(f):
            p=f.root/"input.json";p.write_bytes(b"[]");f.raw["input"]=reference(p,f.root)
        self.mutate(changed)

    def test_same_task_clock_and_direction_order_are_required(self):
        for change in (lambda f:f.raw["directions"].reverse(),
                       lambda f:f.raw["directions"][0].__setitem__("started_nanos","999"),
                       lambda f:f.raw["directions"][0]["cpu"].__setitem__("after_nanos","0"),
                       lambda f:f.raw["directions"][1]["cpu"].__setitem__("before_nanos","149"),
                       lambda f:f.raw["directions"][1]["coarse_thread_cpu"]["before"].__setitem__("user_ticks",9),
                       lambda f:f.raw["directions"][0]["coarse_thread_cpu"]["before"].__setitem__("identity",dict(f.task,thread_id=321))):
            self.mutate(change)

    def test_erased_operations_invented_guest_or_live_types_reject(self):
        for change in (lambda f:f.raw["directions"][0].__setitem__("measured_completed","3"),
                       lambda f:f.raw["directions"][0].__setitem__("observed_arity_or_bytes","13"),
                       lambda f:f.raw.__setitem__("types_dropped",False),lambda f:f.raw.__setitem__("invokes","1")):
            self.mutate(change)


class Reuse(unittest.TestCase):
    def test_attribution_uses_actual_two_codec_frames_and_origin_replay(self):
        with patch.object(allocations.origin,"attribute",return_value={"status":"unavailable"}) as observed:
            self.assertEqual(allocations.attribute(1,2,3,4,5,6),{"status":"unavailable"})
        self.assertEqual(observed.call_args.args,(1,2,3,4,5,6))
        self.assertEqual(observed.call_args.kwargs["symbols"],model.SYMBOLS)
        self.assertIn("decode-or-encode",observed.call_args.kwargs["scope"])

    def test_archive_codec_dispatch_requires_full_replay_and_exact_aggregate(self):
        for kind in ("codec","codec-rpc"):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);value={"schema":f"latent.optimization.{kind}-aggregate.v1","profile":"full","status":"complete","population_complete":True,"attempt_count_complete":True}
                (root/"suite.json").write_bytes(b"{}");(root/"aggregate.json").write_bytes(canonical(value))
                self.assertEqual(archive.evidence_kind(root),kind)
                name="validate_backend_revision_suite" if kind=="codec" else "validate_revision_suite"
                with patch.object(archive,name,return_value=value) as replay:
                    archive.verify_revision(root,codec=kind);replay.assert_called_once()
                changed=dict(value,population_complete=False)
                with patch.object(archive,name,return_value=changed),self.assertRaises(ValueError):archive.verify_revision(root,codec=kind)
                (root/"aggregate.json").write_bytes(canonical(changed))
                with patch.object(archive,name,return_value=changed),self.assertRaises(ValueError):archive.verify_revision(root,codec=kind)
        with self.assertRaises(ValueError):archive.verify_revision(None,ownership="ownership",codec="codec")


if __name__ == "__main__":
    unittest.main()

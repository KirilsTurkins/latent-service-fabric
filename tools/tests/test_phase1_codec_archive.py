"""Small real archive graphs and synthetic capacity envelopes, never benchmarks."""
import copy
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import phase0_evidence
from tools import validate_phase1_archive as verify


class CodecArchiveBounds(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codec-archive-bounds-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, kind, name="source"):
        root = self.root / name
        root.mkdir()
        value = {"schema":f"latent.optimization.{kind}-aggregate.v1", "profile":"full",
                 "status":"complete", "population_complete":True, "attempt_count_complete":True,
                 "synthetic_transport_only":True}
        (root / "aggregate.json").write_bytes(verify.canonical(value))
        (root / "suite.json").write_bytes(b'{"synthetic_transport_only":true}\n')
        (root / "raw.log").write_bytes(b"retained complete bytes\n")
        return root, value

    def envelope(self, root):
        # Declared capacities exercise admission without allocating GiB files.
        aggregate = verify.file_reference(root / "aggregate.json", root)
        rows = [aggregate] + [{"path":f"raw-{i}.log", "bytes":str(256*1024**2),
                              "sha256":"sha256:"+"0"*64} for i in range(4)]
        value = {"schema":"latent.phase1.archive-manifest.v1",
                 "archive":{"path":verify.ARCHIVE,"bytes":"20","sha256":"sha256:"+"0"*64},
                 "files":rows,"total_bytes":str(sum(int(row["bytes"]) for row in rows))}
        (root / verify.MANIFEST).write_text(json.dumps(value),encoding="utf-8")
        return value

    def test_only_codec_accepts_the_bounded_above_one_gib_envelope(self):
        for kind in ("codec", "codec-rpc", "ownership", "ownership-rpc", "revision",
                     "cold", "cache-lookup", "cache-behavior", "budget", "budget-lifecycle",
                     "recovery", "transport-warm", "backend-revision"):
            with self.subTest(kind=kind):
                root,_=self.fixture(kind,kind)
                expected=self.envelope(root)
                if kind == "codec":
                    self.assertEqual(verify.load_manifest(root),expected)
                else:
                    with self.assertRaisesRegex(ValueError,"expanded byte bound"):
                        verify.load_manifest(root)
        self.assertEqual((verify.MAX_COMPRESSED,verify.MAX_SPLIT_COMPRESSED,verify.MAX_FILES),
                         (99_000_000,198_000_000,5000))

    def test_codec_member_and_total_caps_stay_finite(self):
        root,_=self.fixture("codec")
        value=self.envelope(root)
        value["files"][1]["bytes"]=str(256*1024**2+1)
        value["total_bytes"]=str(sum(int(row["bytes"]) for row in value["files"]))
        (root/verify.MANIFEST).write_text(json.dumps(value),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"file exceeds expanded bound"):
            verify.load_manifest(root)
        value=self.envelope(root)
        value["files"] += [dict(value["files"][1],path=f"extra-{i}.log") for i in range(4)]
        value["total_bytes"]=str(sum(int(row["bytes"]) for row in value["files"]))
        (root/verify.MANIFEST).write_text(json.dumps(value),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"expanded byte bound"):
            verify.load_manifest(root)

    def test_real_small_packages_use_codec_override_and_preserve_rpc_default(self):
        for kind in ("codec","codec-rpc"):
            for split in (False,True):
                with self.subTest(kind=kind,split=split):
                    source,value=self.fixture(kind,f"{kind}-{split}")
                    destination=self.root/f"published-{kind}-{split}"
                    validator="validate_backend_revision_suite" if kind=="codec" else "validate_revision_suite"
                    with patch.object(verify,validator,return_value=value) as replay:
                        with patch.object(phase0_evidence,"extract_tar_stream",wraps=phase0_evidence.extract_tar_stream) as extractor:
                            manifest=package.package(source,destination,None,split_archive=split)
                    replay.assert_called_once()
                    expected={"maximum_bytes":2*1024**3} if kind=="codec" else {}
                    self.assertEqual(extractor.call_args.kwargs,expected)
                    self.assertEqual((source/"raw.log").read_bytes(),b"retained complete bytes\n")
                    self.assertEqual(verify.verify_package(destination,replay=False),manifest)

    def test_relabelled_outer_kind_cannot_grant_an_unbound_extraction_cap(self):
        source,value=self.fixture("codec-rpc")
        destination=self.root/"published"
        destination.mkdir()
        package.create_archive(source,destination,None)
        value["schema"]="latent.optimization.codec-aggregate.v1"
        (destination/"aggregate.json").write_bytes(verify.canonical(value))
        with patch.object(phase0_evidence,"extract_tar_stream") as extractor:
            with self.assertRaisesRegex(ValueError,"outer aggregate is not bound"):
                verify.verify_package(destination,replay=False)
            extractor.assert_not_called()
        manifest=json.loads((destination/verify.MANIFEST).read_bytes())
        row=next(row for row in manifest["files"] if row["path"]=="aggregate.json")
        row.update(verify.file_reference(destination/"aggregate.json",destination))
        manifest["total_bytes"]=str(sum(int(row["bytes"]) for row in manifest["files"]))
        (destination/verify.MANIFEST).write_text(json.dumps(manifest),encoding="utf-8")
        with patch.object(phase0_evidence,"extract_tar_stream") as extractor:
            with self.assertRaisesRegex(ValueError,"archive member (size|checksum) mismatch"):
                verify.verify_package(destination,replay=False)
            extractor.assert_not_called()

    def test_rehashed_codec_aggregate_still_requires_exact_full_semantic_replay(self):
        source,value=self.fixture("codec")
        changed=copy.deepcopy(value)
        changed["population_complete"]=False
        with patch.object(verify,"validate_backend_revision_suite",return_value=changed):
            with self.assertRaisesRegex(ValueError,"differs from replayed evidence"):
                package.package(source,self.root/"not-published",None)
        self.assertFalse((self.root/"not-published").exists())

    def test_shared_extractor_rejects_unbounded_overrides_before_creating_output(self):
        for i,limit in enumerate((True,False,0,-1,2*1024**3+1,"2147483648",float(2*1024**3))):
            target=self.root/f"invalid-{i}"
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError,"invalid explicit extraction limit"):
                phase0_evidence.extract_tar_stream(io.BytesIO(),target,"test",maximum_bytes=limit)
            self.assertFalse(target.exists())

    def test_shared_extractor_applies_declared_bound_before_large_body_read(self):
        for name,size,options,reason in (("default",1024**3+1,{},"1073741824-byte extraction limit"),
                                        ("codec",2*1024**3+1,{"maximum_bytes":2*1024**3},"2147483648-byte extraction limit")):
            info=tarfile.TarInfo("raw.log")
            info.size=size
            stream=io.BytesIO(info.tobuf(format=tarfile.USTAR_FORMAT)+b"\0"*1024)
            target=self.root/name
            with self.assertRaisesRegex(ValueError,reason):
                phase0_evidence.extract_tar_stream(stream,target,"test",**options)
            self.assertFalse((target/"raw.log").exists())


if __name__ == "__main__":
    unittest.main()

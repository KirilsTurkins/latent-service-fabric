"""Fixed original-build provenance and refusal before artifact materialization."""
import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import replay_dotnet_published_http as replay


class PublishedHttpReplayTests(unittest.TestCase):
    def origin(self):
        metadata={**replay.ARTIFACT,'expired':False,'workflow_run':{'id':replay.RUN,'head_sha':replay.SOURCE}}
        job={'id':replay.JOB,'run_id':replay.RUN,'head_sha':replay.SOURCE,'status':'completed','conclusion':'failure'}
        return metadata,job

    def test_original_build_origin_never_accepts_a_different_archive_run_head_or_success_claim(self):
        metadata,job=self.origin();replay.validate_origin(metadata,job)
        for owner,key,value in ((0,'digest','sha256:'+'0'*64),(0,'expired',True),
                (1,'run_id',replay.RUN+1),(1,'head_sha','0'*40),(1,'conclusion','success'),(1,'status','in_progress')):
            pair=copy.deepcopy((metadata,job));pair[owner][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,'exact-failed-programme-origin'):
                replay.validate_origin(*pair)

    def test_archive_authentication_refuses_before_any_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'not-created'
            with self.assertRaisesRegex(RuntimeError,'original-archive-sha256'):
                replay.unpack(b'unreviewed archive',output)
            self.assertFalse(output.exists())

    def test_even_a_digest_bound_archive_cannot_escape_the_owned_build_directory(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('published-http/build/../../escape.json',b'{}')
            for i in range(355):archive.writestr('public-'+str(i)+'.json',b'{}')
        raw=stream.getvalue();identity={**replay.ARTIFACT,'size_in_bytes':len(raw),
            'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        with tempfile.TemporaryDirectory() as temporary,patch.object(replay,'ARTIFACT',identity):
            output=Path(temporary)/'not-created'
            with self.assertRaisesRegex(RuntimeError,'regular-public-member'):
                replay.unpack(raw,output)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()

"""The Docker file allowance cannot widen other evidence or byte ceilings."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import phase0_evidence as extraction
from tools import validate_phase1_archive as archive


class DockerBounds(unittest.TestCase):
    def manifest(self, root, kind, count):
        (root/'aggregate.json').write_text(json.dumps({'schema': f'latent.optimization.{kind}-aggregate.v1'}))
        files = [archive.file_reference(root/'aggregate.json', root)]
        files += [{'path': f'empty/{index}', 'bytes': '0', 'sha256': 'sha256:'+'0'*64}
                  for index in range(count-1)]
        value = {'schema':'latent.phase1.archive-manifest.v1',
                 'archive':{'path':archive.ARCHIVE, 'bytes':'0', 'sha256':'sha256:'+'0'*64},
                 'files':files, 'total_bytes':files[0]['bytes']}
        (root/archive.MANIFEST).write_text(json.dumps(value))
        return value

    def test_actual_docker_count_fits_but_6001_and_other_kind_5001_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.manifest(root, 'docker', 5015)
            self.assertEqual(len(archive.load_manifest(root)['files']), 5015)
            for kind, count in (('docker', 6001), ('scheduler', 5001)):
                self.manifest(root, kind, count)
                with self.assertRaisesRegex(ValueError, 'file count'):
                    archive.load_manifest(root)

    def test_docker_discriminator_and_ordinary_file_size_are_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = self.manifest(root, 'docker', 2)
            value['files'][0]['sha256'] = 'sha256:'+'0'*64
            (root/archive.MANIFEST).write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'outer aggregate'):
                archive.load_manifest(root)
            value = self.manifest(root, 'docker', 2)
            value['files'][1]['bytes'] = str(256*1024**2+1)
            value['total_bytes'] = str(sum(int(row['bytes']) for row in value['files']))
            (root/archive.MANIFEST).write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'file exceeds'):
                archive.load_manifest(root)

    def test_extractor_requires_explicit_bounded_member_override(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w', format=tarfile.USTAR_FORMAT) as output:
            for name in ('a', 'b', 'c'):
                output.addfile(tarfile.TarInfo(name), io.BytesIO())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(extraction, 'MAX_ARCHIVE_FILES', 2):
                with self.assertRaisesRegex(ValueError, 'exceeds 2 members'):
                    extraction.extract_tar_stream(io.BytesIO(data.getvalue()), root/'default', 'test')
                self.assertEqual(extraction.extract_tar_stream(io.BytesIO(data.getvalue()), root/'docker',
                                 'test', maximum_files=6000), {'a','b','c'})
            for maximum in (True, 0, 6001):
                with self.assertRaisesRegex(ValueError, 'invalid explicit member limit'):
                    extraction.extract_tar_stream(io.BytesIO(data.getvalue()), root/'invalid',
                                                  'test', maximum_files=maximum)


if __name__ == '__main__':
    unittest.main()

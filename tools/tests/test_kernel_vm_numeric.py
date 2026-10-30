"""Offline retained-origin/initramfs controls; no kernel or VM execution."""
import copy
import unittest

from tools import diagnose_host_stream_kernel_vm as diagnostic


def fixture(init):
    # Explicit synthetic newc mechanics fixture, not a retained Linux image.
    result = bytearray()
    names = ('dev', 'dev/console', 'proc', 'sys', 'init', 'TRAILER!!!')
    modes = (0o40755, 0o20600, 0o40555, 0o40555, 0o100755, 0)
    for ordinal, (name, mode) in enumerate(zip(names, modes)):
        payload = init if name == 'init' else b''
        fields = [721+ordinal, mode, 0, 0, 1, 0, len(payload), 3, 1,
                  5 if name == 'dev/console' else 0, 1 if name == 'dev/console' else 0,
                  len(name)+1, 0]
        result.extend(b'070701'+b''.join(f'{value:08X}'.encode() for value in fields))
        result.extend(name.encode()+b'\0');result.extend(bytes((-len(result))%4))
        result.extend(payload);result.extend(bytes((-len(result))%4))
    result.extend(bytes((-len(result))%512))
    return bytes(result)


class NumericConstructorEvidence(unittest.TestCase):
    def test_original_failure_origin_cannot_be_relabelled_as_a_success_or_different_image(self):
        metadata = dict(id=diagnostic.ARTIFACT, size_in_bytes=diagnostic.ZIP_BYTES,
            digest='sha256:'+diagnostic.ZIP_SHA, expired=False,
            workflow_run=dict(id=diagnostic.RUN, head_sha=diagnostic.SOURCE))
        job = dict(id=diagnostic.JOB, run_id=diagnostic.RUN, head_sha=diagnostic.SOURCE,
                   status='completed', conclusion='failure')
        diagnostic.origin(metadata, job)
        for changes in ({'digest': 'sha256:'+'0'*64}, {'expired': True},
                        {'size_in_bytes': diagnostic.ZIP_BYTES+1}):
            altered = copy.deepcopy(metadata);altered.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                diagnostic.origin(altered, job)
        for changes in ({'conclusion': 'success'}, {'head_sha': '0'*40}, {'run_id': 1}):
            altered = dict(job);altered.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                diagnostic.origin(metadata, altered)

    def test_init_replacement_preserves_every_other_original_entry_and_reproduces_old_payload(self):
        old, new = b'original-init', b'bounded-numeric-init'+bytes(700)
        original = fixture(old)
        self.assertEqual(diagnostic.replace_init(original, old, old), original)
        self.assertEqual(diagnostic.replace_init(original, old, new), fixture(new))
        self.assertEqual(diagnostic.replace_init(fixture(new), new, old), original)

    def test_changed_original_payload_names_headers_and_excess_bytes_are_refused(self):
        old = b'original-init';original = fixture(old)
        for changed in (original.replace(b'070701', b'070702', 1),
                        original.replace(b'console', b'consoLe', 1),
                        original.replace(old, b'changed--init'), original+b'nonzero'):
            with self.subTest(length=len(changed)), self.assertRaises(ValueError):
                diagnostic.replace_init(changed, old, b'new')
        with self.assertRaises(ValueError):
            diagnostic.replace_init(original, old, bytes(diagnostic.image.MAX_INIT+1))

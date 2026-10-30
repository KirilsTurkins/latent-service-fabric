"""Reader/controller controls only; synthetic rows are not native execution."""
import unittest

from tools import qualify_canonical_join_state as owner


class UnorderedOwnerReader(unittest.TestCase):
    def layouts(self):
        return owner.layout_witness(
            b'LSF_WORK_QUEUE_LAYOUT_V1 bytes=136 align=8\n'
            b'LSF_JOIN_STATE_LAYOUT_V1 bytes=80\n'
            b'LSF_FUTURES_BACKING_LAYOUT_V1 task-bytes=128 task-align=8 '
            b'ready-queue-bytes=96 ready-queue-align=8\n')

    def test_compiled_owned_header_witnesses_cannot_be_omitted_or_weakened(self):
        value = self.layouts()
        self.assertEqual((value['taskHeaderBytes'], value['readyQueueHeaderBytes']), (128, 96))
        original = (b'LSF_WORK_QUEUE_LAYOUT_V1 bytes=136 align=8\n'
            b'LSF_JOIN_STATE_LAYOUT_V1 bytes=80\n'
            b'LSF_FUTURES_BACKING_LAYOUT_V1 task-bytes=128 task-align=8 '
            b'ready-queue-bytes=96 ready-queue-align=8\n')
        for changed in (
            original.split(b'LSF_FUTURES_BACKING_LAYOUT_V1')[0],
            original.replace(b'task-bytes=128', b'task-bytes=0'),
            original.replace(b'task-align=8', b'task-align=3'),
            original.replace(b'ready-queue-bytes=96', b'ready-queue-bytes=4097'),
            original + original,
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                owner.layout_witness(changed)

    def test_scoped_actual_sequences_refuse_old_epochs_wrong_owners_and_extra_rows(self):
        # These values test the parser's binding, never grant memory or predict
        # a native layout. The owning programme requires actual compiled output.
        layouts = self.layouts()
        sequence = [136, 136, 128, 96, 64, 80, 72, 88, 48, 136, 136, 128]
        for case in owner.CANONICAL_CASES:
            leaf = case.removeprefix(owner.CANONICAL_PREFIX)
            initialization = leaf.startswith('unordered_initialization_')
            scope = 'initialization' if initialization else 'host'
            shared = 0 if initialization else 2
            lines = []
            for local in owner.CANONICAL_LOCAL[leaf]:
                global_request = local + (2 if initialization else 4)
                lines.extend([
                    f'LSF_CANONICAL_UNORDERED_SEQUENCE_V1 scope={scope} '
                    f'local-owner={local} global-request={global_request} '
                    f'prefix-queue-nodes=2 prefix-shared-headers={shared} '
                    f'bytes={sequence[:global_request]}',
                    f'LSF_CANONICAL_UNORDERED_V1 scope={scope} refusal=memory-bytes '
                    f'local-owner={local} global-request={global_request} '
                    f'prefix-queue-nodes=2 prefix-shared-headers={shared} '
                    'before-poll=true fresh=42 stores=2',
                ])
            if initialization:
                lines.append('LSF_CANONICAL_FUTURES_INITIALIZATION_V1 scenarios=2 '
                    'before-guest=true fresh=42 stores=4')
            raw = ('\n'.join(lines) + '\n').encode()
            with self.subTest(case=case):
                actual = owner.canonical_markers(raw, case, layouts)
                self.assertEqual(len(actual), 2 if initialization else 1)
                for changed in (
                    raw.replace(b'prefix-shared-headers=2', b'prefix-shared-headers=0')
                        if not initialization else raw.replace(b'global-request=3', b'global-request=2'),
                    raw.replace(b'136, 136, 128', b'136, 136, 129'),
                    raw.replace(b'LSF_CANONICAL_UNORDERED_', b'LSF_CANONICAL_QUEUE_'),
                    raw + lines[0].encode() + b'\n',
                    raw + b'LSF_CANONICAL_UNORDERED_SEQUENCE_V1 scope=unknown\n',
                ):
                    with self.assertRaises(ValueError):
                        owner.canonical_markers(changed, case, layouts)


if __name__ == '__main__':
    unittest.main()

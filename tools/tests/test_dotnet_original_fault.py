"""Parser/identity regressions, not evidence of actual NativeAOT execution."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

from tools import dotnet_original_fault as selected
from tools.phase2_operator_process import WorkflowError


def events(frame_count=1):
    rows = []
    for mode in (9, 8):
        frames = [dict(module=index % 2, function=17 + index,
                       moduleOffset=64 + index, functionOffset=index)
                  for index in range(frame_count)]
        rows.append(('DOTNET_ORIGINAL_V3_TRAP', {
            'mode': mode, 'component': selected.COMPONENT,
            'observation': {
                'observedErrors': 1, 'ambiguous': False,
                'trapKind': 'unreachable-code', 'missingBacktrace': False,
                'mayBeTruncated': frame_count == 16, 'observedFrames': frame_count,
                'engineFrameCap': 16, 'frames': frames + [None] * (16 - frame_count),
            },
            'runtimeQualification': False, 'originalFaultCauseQualified': False,
            'opaqueCauseQualified': False, 'fullAC7Qualified': False,
            'full746Qualified': False,
        }))
        rows.append(('DOTNET_ORIGINAL_V3_IDLE', {
            'mode': mode, 'newStores': 1, 'liveStores': 0, 'liveInstances': 0,
            'activeActivations': 0, 'reservedFuel': 0, 'reservedMemory': 0,
            'cpuFuel': 100, 'peakMemoryBytes': 65536,
            'physicalRetirementQualified': False, 'nativeAccountingComplete': False,
        }))
    return rows


def encoded(rows):
    return b'\n'.join(prefix.encode() + b' ' + json.dumps(row).encode()
                      for prefix, row in rows)


class OriginalDotnetFaultTests(unittest.TestCase):
    def test_exact_two_modes_accept_bounded_numeric_frames_without_qualification(self):
        for count in (1, 15, 16):
            with self.subTest(count=count):
                rows = events(count)
                before = copy.deepcopy(rows)
                actual = selected.observations(b'running 1 test\n' + encoded(rows))
                self.assertEqual(actual, [dict(kind=prefix, observation=row)
                                          for prefix, row in rows])
                self.assertEqual(rows, before)
                self.assertFalse(actual[0]['observation']['runtimeQualification'])

    def test_missing_reordered_duplicate_and_extra_events_refuse(self):
        rows = events()
        variants = [rows[:index] + rows[index + 1:] for index in range(4)]
        variants.extend((rows[::-1], rows[2:] + rows[:2], rows + rows[:1],
                         [rows[0], rows[1], rows[0], rows[1]]))
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(WorkflowError):
                selected.observations(encoded(rows))

    def test_exact_mode_component_and_closed_rows_are_required(self):
        for index in range(4):
            cases = [('mode', True), ('mode', 7), ('mode', '9'), ('guestName', 'not-public')]
            if index % 2 == 0:
                cases.append(('component', 'sha256:' + '0' * 64))
            for key, value in cases:
                with self.subTest(index=index, key=key, value=value):
                    rows = events()
                    rows[index][1][key] = value
                    with self.assertRaises(WorkflowError):
                        selected.observations(encoded(rows))

    def test_every_qualification_flag_must_remain_boolean_false(self):
        for index, (_, row) in enumerate(events()):
            for key in row:
                if not (key.endswith('Qualified') or key in
                        ('runtimeQualification', 'nativeAccountingComplete')):
                    continue
                for value in (True, 0, None, 'false'):
                    with self.subTest(index=index, key=key, value=value):
                        rows = events()
                        rows[index][1][key] = value
                        with self.assertRaises(WorkflowError):
                            selected.observations(encoded(rows))

    def test_missing_ambiguous_and_nontrap_observations_refuse(self):
        changes = [('observedErrors', 0), ('observedErrors', 2), ('observedErrors', True),
                   ('ambiguous', True), ('ambiguous', 0), ('trapKind', 'permission-denied'),
                   ('missingBacktrace', True), ('missingBacktrace', 0),
                   ('engineFrameCap', 15), ('engineFrameCap', True),
                   ('observedFrames', 0), ('observedFrames', 17), ('observedFrames', True),
                   ('mayBeTruncated', True), ('mayBeTruncated', 0), ('frames', [None] * 16)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                rows = events()
                rows[0][1]['observation'][key] = value
                with self.assertRaises(WorkflowError):
                    selected.observations(encoded(rows))
        rows = events(16)
        rows[0][1]['observation']['mayBeTruncated'] = False
        with self.assertRaises(WorkflowError):
            selected.observations(encoded(rows))

    def test_frame_identifiers_offsets_and_module_sequence_are_bounded_integers(self):
        changes = [('module', 1), ('module', -1), ('module', True),
                   ('function', -1), ('function', 2**32), ('function', True),
                   ('moduleOffset', -1), ('moduleOffset', 2**32), ('moduleOffset', True),
                   ('functionOffset', -1), ('functionOffset', 2**32), ('functionOffset', True),
                   ('functionName', 'not-public')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                rows = events()
                rows[0][1]['observation']['frames'][0][key] = value
                with self.assertRaises(WorkflowError):
                    selected.observations(encoded(rows))
        rows = events(16)
        rows[0][1]['observation']['frames'][1]['module'] = 2
        with self.assertRaises(WorkflowError):
            selected.observations(encoded(rows))

    def test_frame_tail_and_unknown_snapshot_fields_refuse(self):
        for mutation in ('tail', 'short', 'long', 'extra', 'missing'):
            with self.subTest(mutation=mutation):
                rows = events()
                snapshot = rows[0][1]['observation']
                if mutation == 'tail':
                    snapshot['frames'][-1] = snapshot['frames'][0]
                elif mutation == 'short':
                    snapshot['frames'].pop()
                elif mutation == 'long':
                    snapshot['frames'].append(None)
                elif mutation == 'extra':
                    snapshot['message'] = 'not-public'
                else:
                    del snapshot['trapKind']
                with self.assertRaises(WorkflowError):
                    selected.observations(encoded(rows))

    def test_idle_requires_one_store_zero_live_owners_and_original_consumption_bounds(self):
        changes = [('newStores', 0), ('newStores', 2), ('newStores', True)]
        for key in ('liveStores', 'liveInstances', 'activeActivations',
                    'reservedFuel', 'reservedMemory'):
            changes.extend((key, value) for value in (-1, 1, False))
        for key, cap in (('cpuFuel', selected.BUDGET['cpuFuel']),
                         ('peakMemoryBytes', selected.BUDGET['memoryBytes'])):
            changes.extend((key, value) for value in (0, -1, True, cap + 1))
        for key, value in changes:
            with self.subTest(key=key, value=value):
                rows = events()
                rows[1][1][key] = value
                with self.assertRaises(WorkflowError):
                    selected.observations(encoded(rows))

    def test_duplicate_json_keys_cannot_override_identity_or_flags(self):
        raw = encoded(events())
        for token, replacement in ((b'"mode": 9', b'"mode": 8, "mode": 9'),
                                   (b'"runtimeQualification": false',
                                    b'"runtimeQualification": true, "runtimeQualification": false')):
            with self.subTest(token=token), self.assertRaises(WorkflowError):
                selected.observations(raw.replace(token, replacement, 1))

    def test_output_event_and_prefix_limits_fail_closed(self):
        for raw in (None, '', bytearray(encoded(events())), b'x' * (4 * 1024**2 + 1),
                    b'DOTNET_ORIGINAL_V3_OTHER {}\n' + encoded(events()),
                    b'DOTNET_ORIGINAL_V3_TRAP ' + b' ' * 8256 + b'{}',
                    encoded(events()) + b'\nDOTNET_ORIGINAL_V3_IDLE {}'):
            with self.subTest(type=type(raw)), self.assertRaises(WorkflowError):
                selected.observations(raw)

    def test_truncated_or_counterfeit_archive_refuses_before_restoring_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'original.zip'
            destination = root / 'restored'
            for data in (b'', b'PK\x03\x04' + b'0' * 32):
                archive.write_bytes(data)
                with self.assertRaises(WorkflowError):
                    selected.restore(archive, destination, time.monotonic() + 10)
                self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()

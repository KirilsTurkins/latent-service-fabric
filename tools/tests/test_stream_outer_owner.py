"""Reader controls only; these synthetic rows are not canonical/runtime evidence."""
from pathlib import Path
import tempfile
import unittest

from tools import qualify_stream_outers as owner


class StreamOuterOwnerReader(unittest.TestCase):
    def test_exact_case_success_cannot_be_replaced_by_ignored_wrong_or_duplicate_rows(self):
        for case in (*owner.PRIVATE_CASES, *owner.PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(case=case):
                value = owner.result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-canonical-entry-counter-owner'
                    if case in owner.PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.result(changed, case)
        with self.assertRaises(ValueError):
            owner.result(b'', 'unknown::case')
        for case in (*owner.CONSUMER_PRIVATE_CASES, *owner.CONSUMER_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(consumer_case=case):
                value = owner.consumer_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-consumer-implementation-counter'
                    if case in owner.CONSUMER_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.consumer_result(changed, case)
        for case in (*owner.PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.consumer_result(b'', case)
        for case in (*owner.PRODUCER_PRIVATE_CASES, *owner.PRODUCER_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(producer_case=case):
                value = owner.producer_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-producer-implementation-counter'
                    if case in owner.PRODUCER_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.producer_result(changed, case)
        for case in (*owner.PRIVATE_CASES, *owner.CONSUMER_PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.producer_result(b'', case)
        self.assertEqual((len(owner.FACTORY_PRIVATE_CASES), len(owner.FACTORY_PUBLIC_CASES)), (5, 4))
        self.assertEqual(owner.FACTORY_AFFECTED_PRIVATE_CASES, owner.PRODUCER_PRIVATE_CASES[-1:])
        self.assertEqual(owner.FACTORY_AFFECTED_PUBLIC_CASES, owner.PRODUCER_NEW_PUBLIC_CASES[-2:])
        for case in (*owner.FACTORY_PRIVATE_CASES, *owner.FACTORY_PUBLIC_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(factory_case=case):
                value = owner.factory_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'private-producer-factory-implementation-counter'
                    if case in owner.FACTORY_PRIVATE_CASES else 'public-original-ActivationBudget')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.factory_result(changed, case)
        for case in (*owner.PRIVATE_CASES, *owner.CONSUMER_PRIVATE_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.factory_result(b'', case)
        self.assertEqual((len(owner.IO_CASES), len(owner.IO_NEW_CASES)), (5, 3))
        for index, case in enumerate(owner.IO_CASES):
            raw = (f'test {case} ... ok\n\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 17 filtered out; finished in 0.01s\n').encode()
            with self.subTest(io_case=case):
                value = owner.io_operation_result(raw, case)
                self.assertEqual((value['passed'], value['ignored']), (1, 0))
                self.assertEqual(value['scope'], 'original-Phase3-memory-broker-unit' if index < 3
                    else 'node-compiled-layout-unit' if index == 3 else 'legacy-Phase1-IO-reference')
                for changed in (raw + raw, raw.replace(b'0 ignored', b'1 ignored'),
                    raw.replace(b'1 passed', b'0 passed'),
                    raw.replace(case.encode(), b'wrong::case')):
                    with self.assertRaises(ValueError):
                        owner.io_operation_result(changed, case)
        for case in (*owner.FACTORY_PRIVATE_CASES, *owner.FACTORY_PUBLIC_CASES, 'unknown::case'):
            with self.assertRaises(ValueError):
                owner.io_operation_result(b'', case)

    def test_private_fixture_identity_is_bounded_and_changes_are_observed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture.wasm'
            for raw in (b'', b'not-a-wasm-component', b'\0asm' + b'0' * 65536):
                path.write_bytes(raw)
                with self.assertRaises((ValueError, OSError)):
                    owner.fixture_identity(path)
            # This is a reader identity control, never a parse/runtime claim.
            path.write_bytes(b'\0asm' + b'\x00' * 12)
            first = owner.fixture_identity(path)
            path.write_bytes(b'\0asm' + b'\x01' * 12)
            self.assertNotEqual(owner.fixture_identity(path), first)


if __name__ == '__main__':
    unittest.main()

"""Source/controller checks only; actual LLVM compilation belongs to the hosted producer."""
from __future__ import annotations

import json
import io as byteio
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tarfile
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result
from tools.java_guest import llvm_ssa_io as io, llvm_ssa_patch as patch, llvm_ssa_results as results
from tools.java_guest import llvm_ssa_producer as producer
from tools.java_guest import llvm_ssa_distribution as distribution


class LlvmSsaProducer(unittest.TestCase):
    def test_fixed_host_capacity_reads_ancestor_limits_and_refuses_before_acquisition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = {
                '/proc/meminfo': b'MemTotal: 16777216 kB\nMemAvailable: 12582912 kB\n',
                '/proc/self/cgroup': b'0::/job\n',
                '/sys/fs/cgroup/cpu.max': b'max 100000\n',
                '/sys/fs/cgroup/memory.max': b'max\n',
                '/sys/fs/cgroup/memory.current': str(2 * io.GIB).encode(),
                '/sys/fs/cgroup/job/cpu.max': b'400000 100000\n',
                '/sys/fs/cgroup/job/memory.max': str(15 * io.GIB).encode(),
                '/sys/fs/cgroup/job/memory.current': str(2 * io.GIB).encode(),
            }
            paths = {}
            for ordinal, (name, raw) in enumerate(fixtures.items()):
                paths[name] = root / str(ordinal)
                paths[name].write_bytes(raw)
            original_read = io._capacity_read
            def read(path, maximum):
                if path.as_posix() not in paths:
                    raise FileNotFoundError
                return original_read(paths[path.as_posix()], maximum)
            def observe():
                with mock.patch.object(io, '_capacity_read', side_effect=read), \
                        mock.patch.object(io.os, 'sched_getaffinity', return_value=set(range(4)), create=True), \
                        mock.patch.object(io.os, 'process_cpu_count', return_value=4), \
                        mock.patch.object(Path, 'is_dir', return_value=True), \
                        mock.patch.object(Path, 'is_symlink', return_value=False):
                    return io.host_capacity()
            value = observe()
            self.assertEqual(value['status'], 'admitted')
            self.assertEqual((value['effectiveCpuMilli'], value['effectiveTotalBytes'],
                              value['effectiveAvailableBytes']), (4000, 15 * io.GIB, 12 * io.GIB))
            self.assertEqual(value['cgroupLevels'], 2)
            self.assertFalse(value['hardRssQuota'])
            self.assertFalse(value['memoryFitQualified'])
            for name, raw, reason in [
                ('/sys/fs/cgroup/cpu.max', b'300000 100000', 'insufficient-cpu'),
                ('/sys/fs/cgroup/memory.max', str(11 * io.GIB).encode(), 'insufficient-memory-total'),
                ('/sys/fs/cgroup/job/memory.current', str(7 * io.GIB).encode(), 'insufficient-memory-available'),
                ('/proc/self/cgroup', b'0::/../../escape\n', 'unreadable-or-unsupported'),
                ('/proc/meminfo', b'x' * 65537, 'unreadable-or-unsupported'),
            ]:
                with self.subTest(material=name, reason=reason):
                    paths[name].write_bytes(raw)
                    try:
                        rejected = observe()
                        self.assertEqual((rejected['status'], rejected['reason']), ('refused', reason))
                    finally:
                        paths[name].write_bytes(fixtures[name])
            paths['/sys/fs/cgroup/cpu.max'].write_bytes(b'300000 100000')
            rejected = observe()
            with mock.patch.object(producer, 'admission', return_value={'remainingSeconds': 5400}), \
                    mock.patch.object(io, 'preflight'), mock.patch.object(io, 'case_sensitive'), \
                    mock.patch.object(io, 'host_capacity', return_value=rejected), \
                    mock.patch.object(io, 'acquire') as acquired:
                with self.assertRaisesRegex(ValueError, 'host-capacity'):
                    producer.produce(root / 'refused-build')
                acquired.assert_not_called()
            receipt = json.loads((root / 'refused-build/result.json').read_bytes())
            self.assertEqual(receipt['hostCapacity'], rejected)
            self.assertEqual(receipt['status'], 'failed')
            self.assertNotIn('/sys/fs', json.dumps(rejected))

    def test_generated_cmake_cache_requires_the_exact_ninja_compile_and_link_pools(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache = root / 'CMakeCache.txt'
            raw = (b'CMAKE_GENERATOR:INTERNAL=Ninja\nLLVM_PARALLEL_COMPILE_JOBS:STRING=4\n'
                   b'LLVM_PARALLEL_LINK_JOBS:STRING=1\n')
            cache.write_bytes(raw)
            self.assertEqual(producer.build_pool_values(root), {
                'compileJobs': 4, 'linkJobs': 1, 'cache': {'bytes': len(raw), 'sha256': patch.sha(raw)}})
            for mutant in (raw.replace(b'STRING=4', b'STRING=2'), raw.replace(b'STRING=1', b'STRING=4'),
                           raw.replace(b'=Ninja', b'=Makefiles'), raw + raw, b'x' * (1024 ** 2 + 1)):
                cache.write_bytes(mutant)
                with self.assertRaises(ValueError):
                    producer.build_pool_values(root)

    def original_tree(self, root):
        for name, row in patch.manifest()['files'].items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(row['original'].encode())

    def test_exact_four_preimages_produce_upstream_outputs_and_refuse_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.original_tree(root)
            receipt = patch.apply(root)
            self.assertEqual(receipt['before'], patch.identities('original'))
            self.assertEqual(receipt['after'], patch.identities('modified'))
            self.assertEqual(set(receipt['after']), set(patch.PATHS))
            self.assertEqual(len(patch.unit_cases()), 9)
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                patch.apply(root)
            self.assertEqual(patch.check(root, 'modified'), receipt['after'])

    def test_mutated_last_preimage_refuses_before_any_source_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.original_tree(root)
            last = root / patch.PATHS[-1]
            last.write_bytes(last.read_bytes() + b'// drift\n')
            before = {name: (root / name).read_bytes() for name in patch.PATHS}
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                patch.apply(root)
            self.assertEqual({name: (root / name).read_bytes() for name in patch.PATHS}, before)
            with self.assertRaisesRegex(ValueError, 'patch-stage'):
                patch.check(root, 'unreviewed')

    def test_source_and_output_links_cannot_read_or_package_outside_the_owned_root(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'source'
            root.mkdir()
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'value').write_bytes(b'not a compiler input')
            if os.name == 'nt':
                # Directory junctions exercise the real Windows reparse path
                # without requesting the privileged file-symlink right.
                quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                command = ('New-Item -ItemType Junction -Path ' + quote(root / 'linked')
                           + ' -Target ' + quote(outside) + ' | Out-Null')
                completed = run_bounded_result(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                    cwd=root, env=build_environment(base), timeout_seconds=10, max_output_bytes=4096)
                self.assertEqual(completed.returncode, 0)
            else:
                (root / 'linked').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'patch-link'):
                patch.regular(root, 'linked/value')
            with self.assertRaisesRegex(ValueError, 'output-link'):
                io.inventory(root, 1024, time.monotonic() + 5)
            with self.assertRaisesRegex(ValueError, 'patch-path'):
                patch.regular(root, '../outside/value')
            self.assertEqual((outside / 'value').read_bytes(), b'not a compiler input')

    def test_owned_disk_counting_observes_every_entry_and_checks_real_file_and_entry_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'target').mkdir()
            (root / 'target/header.h').write_bytes(b'12345678901')
            (root / '.git').mkdir()
            (root / '.git/object').write_bytes(b'abc')
            self.assertEqual(io.tree_size(root, 100, deadline=time.monotonic() + 5),
                             {'entries': 4, 'logicalBytes': 14})
            with self.assertRaisesRegex(BuildProcessError, 'disk-bytes'):
                io.tree_size(root, 13, deadline=time.monotonic() + 5)
            with self.assertRaisesRegex(BuildProcessError, 'disk-entries'):
                io.tree_size(root, 100, entries=3, deadline=time.monotonic() + 5)
            with mock.patch.object(io, 'MAX_SINGLE_FILE', 10):
                with self.assertRaisesRegex(BuildProcessError, 'disk-bytes'):
                    io.tree_size(root, 100, deadline=time.monotonic() + 5)
            with mock.patch.object(io.shutil, 'disk_usage', return_value=mock.Mock(free=io.MINIMUM_FREE - 1)):
                with self.assertRaisesRegex(ValueError, 'disk-preflight'):
                    io.preflight(root)

    def test_unit_xml_requires_all_nine_real_case_identities_and_no_disabled_or_duplicate_case(self):
        root = ET.Element('testsuites', tests='9', failures='0', disabled='0', errors='0')
        suite = ET.SubElement(root, 'testsuite', name='SSAUpdaterBulk')
        for full in patch.unit_cases():
            ET.SubElement(suite, 'testcase', classname='SSAUpdaterBulk', name=full.split('.', 1)[1],
                          status='run', result='completed')
        self.assertEqual(results.units(ET.tostring(root))['passed'], 9)
        suite[0].set('status', 'notrun')
        with self.assertRaisesRegex(ValueError, 'unit-not-executed'):
            results.units(ET.tostring(root))
        suite[0].set('status', 'run')
        suite[-1].set('name', suite[0].get('name'))
        with self.assertRaisesRegex(ValueError, 'unit-case-set'):
            results.units(ET.tostring(root))
        with self.assertRaisesRegex(ValueError, 'xml-bound'):
            results.units(b'<!DOCTYPE testsuites><testsuites/>')

    def test_operational_disk_sample_tolerates_only_actual_disappearing_entries_and_child_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'stable').write_bytes(b'kept')
            real_scandir = io.os.scandir
            def disappearing_file(directory):
                scan = real_scandir(directory)
                class Race:
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        scan.close()
                    def __iter__(self):
                        for row in scan:
                            if row.name == 'vanishing':
                                (root / row.name).unlink()
                            # Windows DirEntry may cache its enumeration stat.
                            # Force a real filesystem stat after the deletion,
                            # matching the producer's Linux race boundary.
                            class ActualEntry:
                                name, path = row.name, row.path
                                def stat(self, *, follow_symlinks):
                                    return Path(self.path).stat(follow_symlinks=follow_symlinks)
                            yield ActualEntry()
                return Race()
            for operational in (False, True):
                (root / 'vanishing').write_bytes(b'gone before stat')
                with mock.patch.object(io.os, 'scandir', side_effect=disappearing_file):
                    if operational:
                        self.assertEqual(io.tree_size(root, 100, deadline=time.monotonic() + 5,
                                                      operational=True), {'entries': 1, 'logicalBytes': 4})
                    else:
                        with self.assertRaises(FileNotFoundError):
                            io.tree_size(root, 100, deadline=time.monotonic() + 5)
            def disappearing_directory(directory):
                if directory == root / 'vanishing-dir':
                    directory.rmdir()
                return real_scandir(directory)
            for operational in (False, True):
                (root / 'vanishing-dir').mkdir()
                with mock.patch.object(io.os, 'scandir', side_effect=disappearing_directory):
                    if operational:
                        value = io.tree_size(root, 100, deadline=time.monotonic() + 5, operational=True)
                        self.assertEqual(value, {'entries': 2, 'logicalBytes': 4})
                    else:
                        with self.assertRaises(FileNotFoundError):
                            io.tree_size(root, 100, deadline=time.monotonic() + 5)
            real_readlink = io.os.readlink
            link = root / 'vanishing-link'
            for operational in (False, True):
                shim_link_stat = False
                try:
                    link.symlink_to('stable')
                except OSError as error:
                    if os.name != 'nt' or getattr(error, 'winerror', None) != 1314:
                        raise
                    # Windows may lack the privileged symlink right. Delete a
                    # real file after stat, while shimming only its link kind;
                    # the supported Linux producer always uses a real symlink.
                    link.write_bytes(b'gone before readlink')
                    shim_link_stat = True
                if not operational:
                    print('readlink disappearance control: ' + (
                        'Windows actual file deletion with link-stat/readlink exception shims'
                        if shim_link_stat else 'actual filesystem symlink deletion'))
                def link_scandir(directory):
                    scan = real_scandir(directory)
                    class Race:
                        def __enter__(self):
                            return self
                        def __exit__(self, *args):
                            scan.close()
                        def __iter__(self):
                            for row in scan:
                                class ActualEntry:
                                    name, path = row.name, row.path
                                    def stat(self, *, follow_symlinks):
                                        info = Path(self.path).stat(follow_symlinks=follow_symlinks)
                                        if shim_link_stat and self.name == link.name:
                                            return mock.Mock(st_mode=stat.S_IFLNK)
                                        return info
                                yield ActualEntry()
                    return Race()
                def disappearing_link(path):
                    if Path(path) == link:
                        link.unlink()
                        if shim_link_stat:
                            # This boundary is a shim on Windows; deletion and
                            # the missing path are still real filesystem state.
                            self.assertFalse(link.exists())
                            raise FileNotFoundError(str(link))
                    return real_readlink(path)
                with mock.patch.object(io.os, 'scandir', side_effect=link_scandir), \
                        mock.patch.object(io.os, 'readlink', side_effect=disappearing_link):
                    if operational:
                        self.assertEqual(io.tree_size(root, 100, deadline=time.monotonic() + 5,
                                                      operational=True), {'entries': 2, 'logicalBytes': 4})
                    else:
                        with self.assertRaises(FileNotFoundError):
                            io.tree_size(root, 100, deadline=time.monotonic() + 5)
            with mock.patch.object(io.os, 'scandir', side_effect=PermissionError('refuse')):
                with self.assertRaises(PermissionError):
                    io.tree_size(root, 100, deadline=time.monotonic() + 5, operational=True)
            with self.assertRaisesRegex(ValueError, 'tree-root'):
                io.tree_size(root / 'missing-root', 100, deadline=time.monotonic() + 5, operational=True)

    def test_lit_xml_keeps_all_original_sjlj_files_and_refuses_skips_or_missing_cases(self):
        root = ET.Element('testsuites', tests='13', failures='0', skipped='0')
        suite = ET.SubElement(root, 'testsuite', name='LLVM')
        for row in results.selection()['wasmTests']:
            ET.SubElement(suite, 'testcase', classname='LLVM.CodeGen/WebAssembly',
                          name=Path(row['path']).name, time='0.1')
        self.assertEqual(results.lit(ET.tostring(root))['passed'], 13)
        ET.SubElement(suite[0], 'skipped')
        with self.assertRaisesRegex(ValueError, 'test-not-passed'):
            results.lit(ET.tostring(root))
        suite[0].remove(suite[0][0])
        suite.remove(suite[0])
        with self.assertRaisesRegex(ValueError, 'lit-case-set'):
            results.lit(ET.tostring(root))

    def test_cross_pass_parser_rejects_unlowered_setjmp_and_phis_before_catchswitch(self):
        # Synthetic bounded parser input, not an executed LLVM/guest result.
        raw = b'''define void @test() {
entry:
  call void @__wasm_setjmp()
  invoke void @may_throw() to label %done unwind label %dispatch
dispatch:
  %cs = catchswitch within none [label %catch] unwind to caller
catch:
  %cp = catchpad within %cs [ptr null]
  catchret from %cp to label %done
done:
  ret void
}
'''
        self.assertEqual(results.cross_pass(raw)['catchswitchPhis'], 0)
        with self.assertRaisesRegex(ValueError, 'catchswitch-phi'):
            results.cross_pass(raw.replace(b'dispatch:\n', b'dispatch:\n  %v = phi i32 [0, %entry]\n'))
        with self.assertRaisesRegex(ValueError, 'cross-pass-shape'):
            results.cross_pass(raw.replace(b'call void @__wasm_setjmp()', b'%a = call i32 @setjmp(ptr null)'))

    def test_archive_metadata_preserves_case_distinct_sources_but_refuses_escape_duplicates_and_oversized_files(self):
        policy = io.SOURCES['llvm']
        prefix = policy['prefix']
        def carrier(rows):
            data = byteio.BytesIO()
            for name, size in rows:
                info = tarfile.TarInfo(name)
                info.size = size
                data.write(info.tobuf(format=tarfile.USTAR_FORMAT))
                # An intentionally incomplete huge member tests refusal at its
                # actual tar header, before payload access or extraction.
                if size < 100:
                    data.write(b'x' * size + b'\0' * ((-size) % 512))
            data.write(b'\0' * 1024)
            data.seek(0)
            return tarfile.open(fileobj=data)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'extract'
            with carrier([(prefix + '/Header.h', 1), (prefix + '/header.h', 1)]) as archive:
                io.validate_members(archive, policy, target, time.monotonic() + 5)
            for rows, reason in [([(prefix + '/../escape', 1)], 'archive-member'),
                                 ([(prefix + '/a', 1), (prefix + '/a', 1)], 'archive-member'),
                                 ([(prefix + '/big', policy['maximumFile'] + 1)], 'archive-bound')]:
                with self.subTest(rows=rows), carrier(rows) as archive:
                    with self.assertRaisesRegex(ValueError, reason):
                        io.validate_members(archive, policy, target, time.monotonic() + 5)
            self.assertFalse(target.exists())
            self.assertFalse((Path(folder) / 'escape').exists())

    def test_archive_authentication_refuses_unknown_sources_and_modified_bytes_before_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'fixture.tar'
            archive.write_bytes(b'wrong')
            policy = {**io.SOURCES['sdk'], 'bytes': 5, 'sha256': patch.sha(b'right')}
            with mock.patch.dict(io.SOURCES, {'sdk': policy}):
                with self.assertRaisesRegex(ValueError, 'archive-identity'):
                    io.extract('sdk', archive, root / 'extract', time.monotonic() + 5)
            self.assertFalse((root / 'extract').exists())
            with self.assertRaisesRegex(ValueError, 'source-kind'):
                io.acquire('arbitrary-url', root / 'uncreated', time.monotonic() + 5)
            self.assertFalse((root / 'uncreated').exists())

    def test_hosted_admission_uses_real_repository_head_and_refuses_other_event_workflow_or_output_before_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder).resolve()
            head = run_bounded_result(['git', 'rev-parse', 'HEAD'], cwd=patch.ROOT,
                                      env=build_environment(temp), timeout_seconds=10,
                                      max_output_bytes=4096).stdout.decode().strip()
            env = {'GITHUB_REPOSITORY': producer.REPOSITORY, 'GITHUB_EVENT_NAME': 'push',
                   'GITHUB_WORKSPACE': str(patch.ROOT), 'GITHUB_SHA': head, 'GITHUB_WORKFLOW_SHA': head,
                   'GITHUB_REF': 'refs/heads/' + producer.BRANCH, 'RUNNER_TEMP': str(temp),
                   'GITHUB_WORKFLOW_REF': producer.REPOSITORY + '/' + producer.WORKFLOW + '@refs/heads/' + producer.BRANCH,
                   'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
                   'LSF_LLVM_PRODUCER_STARTED': str(int(time.time()))}
            output = temp / 'java-llvm-ssa-producer'
            # Test the actual context predicate on this platform; this is not a
            # claim that Windows is a supported compiler-producing host.
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(producer.sys, 'platform', 'linux'), \
                    mock.patch.object(producer.platform, 'machine', return_value='x86_64'):
                self.assertEqual(producer.admission(output)['sourceCommit'], head)
                for key, value in [('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_REF', 'refs/heads/other'),
                                   ('GITHUB_WORKFLOW_SHA', '0' * 40),
                                   ('GITHUB_WORKFLOW_REF', 'other/workflow')]:
                    with self.subTest(key=key), mock.patch.dict(os.environ, {key: value}):
                        with self.assertRaisesRegex(ValueError, 'hosted-source-context'):
                            producer.admission(output)
                with self.assertRaisesRegex(ValueError, 'hosted-source-context'):
                    producer.admission(temp / 'arbitrary')
            self.assertFalse(output.exists())

    def test_actual_command_adapter_refuses_expired_start_and_zero_exit_after_aggregate_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clock = mock.Mock(return_value=10.0)
            with mock.patch.object(producer.time, 'monotonic', clock):
                run = producer.Commands(root, 20.0)
                clock.return_value = 21.0
                with mock.patch.object(build_process := producer.build_process, '_run_owned') as owned:
                    with self.assertRaisesRegex(ValueError, 'producer-deadline'):
                        run.run('expired', os.sys.executable, '--version')
                    owned.assert_not_called()
                clock.return_value = 10.0
                def late_exit(*args, **kwargs):
                    clock.return_value = 21.0
                    return subprocess.CompletedProcess(args[0], 0, b'', b'')
                with mock.patch.object(build_process, '_run_owned', side_effect=late_exit), \
                        mock.patch.object(io.shutil, 'disk_usage', return_value=mock.Mock(free=io.MINIMUM_FREE)):
                    with self.assertRaisesRegex(BuildProcessError, 'producer-deadline'):
                        run.run('late-zero-exit', os.sys.executable, '--version')
                self.assertEqual(run.records[-1]['exitCode'], 0)
                self.assertEqual(run.records[-1]['postCheckFailure'], 'llvm-producer-deadline')

    def test_actual_ninja_log_counts_and_deadline_metadata_do_not_claim_target_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'build').mkdir()
            log = root / 'build/.ninja_log'
            rows = (b'# ninja log v7\n1\t2\t3\ttools/clang/a.o\tabc\n'
                    b'2\t3\t4\tbin/llvm-config\tabd\n'
                    b'3\t4\t5\ttools/clang/a.o\tabe\n'
                    b'4\t5\t6\tunittests/Transforms/Utils/CMakeFiles/UtilsTests.dir/SSAUpdaterBulkTest.cpp.o\tabf\n')
            log.write_bytes(rows)
            progress = producer.ninja_progress(root, time.monotonic() + 10)
            self.assertEqual((progress['completedLogRows'], progress['uniqueOutputs']), (4, 3))
            self.assertEqual(progress['latestEndMilliseconds'], 5)
            self.assertEqual((progress['clangObjectRows'], progress['utilsTestObjectRows']), (2, 1))
            self.assertTrue(progress['loggedTargets']['llvm-config'])
            self.assertFalse(progress['loggedTargets']['clang'])
            self.assertFalse(progress['loggedTargets']['UtilsTests'])
            self.assertNotIn('tools/clang/a.o', json.dumps(progress))
            log.write_bytes(rows + b'partial')
            self.assertEqual(producer.ninja_progress(root, time.monotonic() + 10)['status'], 'incomplete')
            for mutant in (b'# ninja log v5\n', rows + b'bad\n', rows + b'x' * 4097 + b'\n'):
                log.write_bytes(mutant)
                self.assertEqual(producer.ninja_progress(root, time.monotonic() + 10)['status'], 'incomplete')
            log.write_bytes(rows)
            run = producer.Commands(root, time.monotonic() + 10)
            with mock.patch.object(io.shutil, 'disk_usage', return_value=mock.Mock(free=io.MINIMUM_FREE)):
                with self.assertRaisesRegex(BuildProcessError, '^command-deadline$'):
                    run.run('build-reviewed-llvm-and-tests', os.sys.executable, '-c',
                            'import time; time.sleep(5)', seconds=0.05)
            self.assertEqual(run.records[-1]['failure'], 'command-deadline')
            self.assertIsNone(run.records[-1]['exitCode'])
            self.assertEqual(run.records[-1]['buildProgress'], progress)
            self.assertNotIn('stdout', run.records[-1])

    def test_typed_carrier_roundtrip_preserves_modes_links_and_refuses_unknown_or_over_bound_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            products = root / 'products'
            binary = products / 'toolchain/bin/clang-21'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'actual small compiler-carrier fixture\n')
            binary.chmod(0o751)
            for name in distribution.TOP - {'toolchain'}:
                (products / name).write_bytes(name.encode())
            if os.name != 'nt':
                # Actual filesystem link creation/extraction is mandatory on
                # the supported Linux producer, never a skipped source case.
                (binary.parent / 'clang').symlink_to('clang-21')
            deadline = time.monotonic() + 10
            receipt = distribution.create(root, '1' * 40, deadline)
            value = json.loads((root / distribution.MANIFEST).read_bytes())
            distribution.verify_carrier(root, distribution.ARCHIVE, value, deadline)
            with tarfile.open(root / distribution.ARCHIVE) as carrier:
                member = carrier.getmember('toolchain/bin/clang-21')
                self.assertEqual(member.mode, binary.stat().st_mode & 0o777)
                self.assertEqual(carrier.extractfile(member).read(), binary.read_bytes())
                if os.name != 'nt':
                    unpacked = root / 'unpacked'
                    carrier.extractall(unpacked, filter='data')
                    self.assertEqual((unpacked / member.name).stat().st_mode & 0o777, 0o751)
                    self.assertTrue((unpacked / 'toolchain/bin/clang').is_symlink())
                    self.assertEqual(os.readlink(unpacked / 'toolchain/bin/clang'), 'clang-21')
            # Portable tar-container roundtrip covers link headers even on
            # Windows without requiring its privileged file-symlink API.
            linked = json.loads(json.dumps(value))
            linked['members']['toolchain/bin/clang-alias'] = {
                'kind': 'symlink', 'mode': 0o777, 'link': 'clang-21'}
            distribution.write_carrier(products, root / 'link-control.tar.gz', linked, deadline)
            distribution.verify_carrier(root, 'link-control.tar.gz', linked, deadline)
            with tarfile.open(root / 'link-control.tar.gz') as carrier:
                alias = carrier.getmember('toolchain/bin/clang-alias')
                self.assertTrue(alias.issym())
                self.assertEqual((alias.mode, alias.linkname), (0o777, 'clang-21'))
            linked['members']['toolchain/bin/clang-alias']['link'] = '../../../outside'
            with self.assertRaisesRegex(ValueError, 'carrier-link'):
                distribution.validate_manifest(linked, deadline)
            with mock.patch.object(distribution, 'CARRIER_BYTES', receipt['archive']['bytes'] - 1):
                with self.assertRaisesRegex(ValueError, 'file-bound'):
                    distribution.verify_carrier(root, distribution.ARCHIVE, value, deadline)
            decoded = json.loads(json.dumps(value))
            with mock.patch.object(io, 'PRODUCT_BYTES', receipt['decodedLogicalBytes'] - 256):
                decoded['decodedByteLimit'] = io.PRODUCT_BYTES
                with self.assertRaisesRegex(ValueError, 'decoded-bound'):
                    distribution.validate_manifest(decoded, deadline)
            with tarfile.open(root / distribution.ARCHIVE) as original, \
                    tarfile.open(root / 'unknown-control.tar.gz', 'w:gz') as changed:
                for member in original:
                    changed.addfile(member, original.extractfile(member) if member.isfile() else None)
                unknown = tarfile.TarInfo('unexpected')
                unknown.mode, unknown.size = 0o644, 1
                changed.addfile(unknown, byteio.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError, 'member-set'):
                distribution.verify_carrier(root, 'unknown-control.tar.gz', value, deadline)
            result = {'schemaVersion': 'latent.java.llvm-sjlj-producer.v1', 'status': 'passed',
                      'source': {'sourceCommit': '1' * 40}, 'profile': distribution.PROFILE,
                      'distribution': receipt}
            (root / 'result.json').write_bytes(distribution.encode(result))
            admitted = distribution.admit_upload(root, '1' * 40, deadline)
            self.assertTrue(admitted['qualifiedCompiler'])
            with mock.patch.object(distribution, 'METADATA_BYTES', 1):
                with self.assertRaisesRegex(ValueError, 'metadata-bound'):
                    distribution.admit_upload(root, '1' * 40, deadline)
            commands = root / 'commands'
            commands.mkdir()
            (commands / 'unknown').write_bytes(b'not an admitted log')
            with self.assertRaisesRegex(ValueError, 'command-member'):
                distribution.admit_upload(root, '1' * 40, deadline)
            (commands / 'unknown').unlink()
            (root / 'upload-admission.json').unlink()
            result['status'] = 'failed'
            (root / 'result.json').write_bytes(distribution.encode(result))
            self.assertFalse(distribution.admit_upload(root, '1' * 40, deadline)['qualifiedCompiler'])
            self.assertFalse((root / distribution.ARCHIVE).exists())
            self.assertEqual(patch.sha((root / 'unqualified-derived-sdk.tar.gz').read_bytes()),
                             receipt['archive']['sha256'])
            (products / 'unknown').write_bytes(b'not an admitted SDK member')
            with self.assertRaisesRegex(ValueError, 'product-set'):
                distribution.payload_rows(products, deadline)


if __name__ == '__main__':
    unittest.main()

"""Small actual carriers and codec refusals; no LLVM, JVM or guest execution.

Producer receipts/XML below are explicitly synthetic controller fixtures. Only
the future immutable successful GitHub tuple may admit a real compiler.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest import mock
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tools.java_guest.compiler import Compiler
from tools.java_guest import llvm_ssa_consumer as consumer
from tools.java_guest import llvm_ssa_consumer_inputs as inputs
from tools.java_guest import llvm_ssa_distribution as carrier
from tools.java_guest import llvm_ssa_io as io, llvm_ssa_patch as patch
from tools.java_guest import llvm_ssa_producer as producer, llvm_ssa_results as results
from tools.ci_lane_inventory import workflow_model
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result


class LlvmSsaConsumer(unittest.TestCase):
    def test_real_small_core_framing_counts_imports_bodies_and_fixed_pools_name(self):
        # Valid tiny core encoding, inspected as bytes only; no executable tool
        # or synthetic claim that the original public Capsule assembled.
        section = lambda kind, data: bytes([kind, len(data)]) + data
        prefix = (b'\0asm\1\0\0\0' + section(1, b'\1\x60\0\0')
                  + section(2, b'\1\3env\1f\0\0'))
        functions = section(3, b'\2\0\0')
        code = section(10, b'\2\2\0\x0b\3\0\1\x0b')
        label = b'meth_dla_Capsule_pools'
        names = b'\1\2' + bytes([len(label)]) + label
        custom = section(0, b'\4name' + section(1, names))
        raw = prefix + functions + code + custom
        inventory = consumer.body_inventory(raw)
        self.assertEqual((inventory['importedFunctions'], inventory['definedFunctions']), (1, 2))
        self.assertEqual(inventory['largest']['functionIndex'], 2)
        self.assertEqual(inventory['largest']['bytes'], 3)
        self.assertEqual(raw[inventory['largest']['start']:inventory['largest']['end']], b'\0\1\x0b')
        self.assertEqual(inventory['pools']['status'], 'named')
        self.assertEqual(inventory['pools']['functionIndex'], 2)
        self.assertEqual(consumer.body_inventory(prefix + functions + code)['pools'],
                         {'status': 'name-unavailable'})
        with self.assertRaisesRegex(ValueError, 'core-function-count'):
            consumer.body_inventory(prefix + section(3, b'\3\0\0\0') + code)
        with self.assertRaises(ValueError):
            consumer.body_inventory(raw[:-1])
        duplicate = b'\2' + names[1:] + names[1:]
        with self.assertRaisesRegex(ValueError, 'core-duplicate-name'):
            consumer.body_inventory(prefix + functions + code
                                    + section(0, b'\4name' + section(1, duplicate)))

    def test_original_public_job_defaults_and_complete_command_recipe_remain_exact(self):
        model = workflow_model((patch.ROOT / '.github/workflows/java-guest-feasibility.yml').read_text())
        job = copy.deepcopy(model['jobs']['public-fiber-assembly'])
        # Invert ONLY the explicit R8 additions before the original R7/default
        # preservation oracle below. Every removed route/pin is asserted first.
        self.assertEqual(model['on']['workflow_dispatch']['inputs']['public_fiber_private_scalar_llvm'], {
            'description': 'Compiler-only public fixture using the independently qualified private-scalar backend',
            'type': 'boolean', 'default': False})
        self.assertEqual(job['if'], "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm || inputs.public_fiber_private_scalar_llvm) }}")
        job['if'] = "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}"
        mode = job['steps'][0]
        self.assertEqual(mode['env'].pop('PUBLIC_FIBER_PRIVATE_SCALAR_LLVM'), '${{ inputs.public_fiber_private_scalar_llvm }}')
        for clause in ("        or os.environ.get('PUBLIC_FIBER_PRIVATE_SCALAR_LLVM', 'false') not in ('true', 'false')\n",
                "        or (os.environ['PUBLIC_FIBER_DERIVED_LLVM'] == 'true' and os.environ.get('PUBLIC_FIBER_PRIVATE_SCALAR_LLVM', 'false') == 'true')\n"):
            self.assertEqual(mode['run'].count(clause), 1)
            mode['run'] = mode['run'].replace(clause, '', 1)
        selected = "if os.environ['PUBLIC_FIBER_DERIVED_LLVM'] == 'true' or os.environ.get('PUBLIC_FIBER_PRIVATE_SCALAR_LLVM', 'false') == 'true':"
        self.assertEqual(mode['run'].count(selected), 1)
        mode['run'] = mode['run'].replace(selected, "if os.environ['PUBLIC_FIBER_DERIVED_LLVM'] == 'true':", 1)
        added = {'Install the same prerequisites for the separately admitted private-scalar backend',
                 'Compile the unchanged public C with the independently qualified backend'}
        self.assertEqual(sum(s.get('name') in added for s in job['steps']), 2)
        job['steps'] = [s for s in job['steps'] if s.get('name') not in added]
        for step in job['steps']:
            if step.get('name') in {'Install only the same pinned normal public component compiler',
                                   'Prepare only the unchanged public fibers and original JDK controls'}:
                self.assertEqual(step['if'], '${{ !inputs.public_fiber_derived_llvm && !inputs.public_fiber_private_scalar_llvm }}')
                step['if'] = '${{ !inputs.public_fiber_derived_llvm }}'
        for suffix in ('producer-run.json', 'producer-job.json', 'producer-artifact.json', 'derived-sdk-manifest.json',
                       'products/NOTICE', 'products/LLVM-LICENSE.txt', 'products/LLVM-PATCH.json',
                       'products/LLVM-PRIVATE-STORES.json'):
            line = '${{ runner.temp }}/java-llvm-private-stores-inputs/' + suffix + '\n'
            self.assertEqual(job['steps'][-1]['with']['path'].count(line), 1)
            job['steps'][-1]['with']['path'] = job['steps'][-1]['with']['path'].replace(line, '', 1)
        self.assertEqual(model['on']['workflow_dispatch']['inputs']['public_fiber_derived_llvm'], {
            'description': 'Compiler-only public fixture using one qualified source-bound LLVM candidate',
            'type': 'boolean', 'default': False})
        self.assertEqual(job.pop('permissions'), {'contents': 'read', 'actions': 'read'})
        self.assertEqual(job['if'], "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}")
        job['if'] = "${{ github.event_name == 'workflow_dispatch' && inputs.public_fiber_assembly }}"
        first = job['steps'][0]
        self.assertEqual(first['env'].pop('PUBLIC_FIBER_DERIVED_LLVM'), '${{ inputs.public_fiber_derived_llvm }}')
        clause = "        or os.environ['PUBLIC_FIBER_DERIVED_LLVM'] not in ('true', 'false')\n"
        self.assertEqual(first['run'].count(clause), 1)
        first['run'] = first['run'].replace(clause, '', 1)
        stamp = ("if os.environ['PUBLIC_FIBER_DERIVED_LLVM'] == 'true':\n"
                 "    if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'\n"
                 "            or os.environ.get('GITHUB_REF') != 'refs/heads/feat/java-llvm-ssa-consumer-20261025'):\n"
                 "        raise SystemExit('derived LLVM public compiler requires its explicit feature ref')\n"
                 "    import time\n"
                 "    with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:\n"
                 "        output.write('LSF_JAVA_LLVM_PUBLIC_STARTED=' + str(int(time.time())) + '\\n')\n")
        self.assertEqual(first['run'].count(stamp), 1)
        first['run'] = first['run'].replace(stamp, '', 1)
        defaults = {'Install only the same pinned normal public component compiler',
                    'Prepare only the unchanged public fibers and original JDK controls'}
        additions = {'Install the same public compiler prerequisites for the qualified LLVM candidate',
                     'Compile only the same public fixture using its authenticated LLVM candidate'}
        self.assertEqual(sum(s.get('name') in additions for s in job['steps']), 2)
        job['steps'] = [s for s in job['steps'] if s.get('name') not in additions]
        for step in job['steps']:
            if step.get('name') in defaults:
                self.assertEqual(step.pop('if'), '${{ !inputs.public_fiber_derived_llvm }}')
        retention = job['steps'][-1]['with']
        for suffix in ('java-activation-fibers/compiler-inputs.json',
                'java-activation-fibers/build/derived-public-products/**',
                'java-activation-fibers/compiler/public-copy-cost-candidate.json',
                'java-activation-fibers/compiler/public-wineh-preclang.json',
                'java-activation-fibers/compiler/public-copy-cost-Capsule.c',
                'java-activation-fibers/compiler/coroutine-compiler-preparation.json',
                'java-activation-fibers/build/project/compiler-patch/loaded.json',
                'java-activation-fibers/build/coroutine-compiler-profile.json',
                'java-activation-fibers/src/Capsule.java',
                'java-activation-fibers/wit/service.wit',
                'java-llvm-public-inputs/producer-run.json', 'java-llvm-public-inputs/producer-job.json',
                'java-llvm-public-inputs/producer-artifact.json', 'java-llvm-public-inputs/derived-sdk-manifest.json',
                'java-llvm-public-inputs/products/NOTICE', 'java-llvm-public-inputs/products/LLVM-LICENSE.txt',
                'java-llvm-public-inputs/products/LLVM-PATCH.json'):
            line = '${{ runner.temp }}/' + suffix + '\n'
            self.assertEqual(retention['path'].count(line), 1)
            retention['path'] = retention['path'].replace(line, '', 1)
        baseline = hashlib.sha256(json.dumps(job, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(baseline, 'bd9edf4ce8987000fa8e170932bafde9e8e65358fe6dde8cd59d489f904b185c')

    def test_actual_workflow_selector_refuses_mixed_or_nonboolean_modes_before_acquisition(self):
        model = workflow_model((patch.ROOT / '.github/workflows/java-guest-feasibility.yml').read_text())
        first = model['jobs']['public-fiber-assembly']['steps'][0]
        self.assertEqual(first['id'], 'public-fiber-mode')
        lines = first['run'].splitlines()
        self.assertEqual((lines[0], lines[-1]), ("python3 - <<'PY'", 'PY'))
        script = '\n'.join(lines[1:-1])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cases = [(p, d, s, h) for p in ('true', 'false') for d in ('true', 'false')
                     for s in ('true', 'false') for h in ('true', 'false')]
            cases += [('true', value, 'false', 'false') for value in ('1', 'True', 'unknown')]
            for ordinal, (public, derived, scratch, http) in enumerate(cases):
                with self.subTest(values=(public, derived, scratch, http)):
                    target = root / (str(ordinal) + '.env')
                    env = build_environment(root)
                    env.update(PUBLIC_FIBER_ASSEMBLY=public, PUBLIC_FIBER_DERIVED_LLVM=derived,
                               QUALIFY_SCRATCH_REFUSALS=scratch, JAVA_HTTP_SPI=http, GITHUB_ENV=str(target),
                               GITHUB_EVENT_NAME='workflow_dispatch',
                               GITHUB_REF='refs/heads/' + inputs.CONSUMER_BRANCH)
                    result = run_bounded_result([sys.executable, '-B', '-c', script], cwd=root, env=env,
                                               timeout_seconds=5, max_output_bytes=4096)
                    accepted = public == 'true' and derived in ('true', 'false') and scratch == http == 'false'
                    self.assertEqual(result.returncode == 0, accepted)
                    if accepted and derived == 'true':
                        self.assertRegex(target.read_text(), r'^LSF_JAVA_LLVM_PUBLIC_STARTED=[0-9]{10}\n$')
                    else:
                        self.assertFalse(target.exists())
            for event, ref in [('push', 'refs/heads/' + inputs.CONSUMER_BRANCH),
                               ('workflow_dispatch', 'refs/heads/release'),
                               ('workflow_dispatch', 'refs/tags/ambiguous'),
                               ('workflow_dispatch', '')]:
                with self.subTest(event=event, ref=ref):
                    target = root / 'refused.env'
                    env = build_environment(root)
                    env.update(PUBLIC_FIBER_ASSEMBLY='true', PUBLIC_FIBER_DERIVED_LLVM='true',
                               QUALIFY_SCRATCH_REFUSALS='false', JAVA_HTTP_SPI='false',
                               GITHUB_ENV=str(target), GITHUB_EVENT_NAME=event, GITHUB_REF=ref)
                    result = run_bounded_result([sys.executable, '-B', '-c', script], cwd=root, env=env,
                                               timeout_seconds=5, max_output_bytes=4096)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b'derived LLVM public compiler requires its explicit feature ref',
                                  result.stdout + result.stderr)
                    self.assertFalse(target.exists())

    def fixture(self, root):
        # The unfilled production pin remains untouched. Bind this fixture's
        # actual current recipe bytes only for this source-control invocation.
        recipe = producer.recipe()
        recipe_pin = mock.patch.object(inputs, 'RECIPE_SHA', patch.sha(carrier.encode(recipe)))
        recipe_pin.start()
        self.addCleanup(recipe_pin.stop)
        directory = root / 'synthetic-producer'
        products = directory / 'products'
        original = root / 'synthetic-original'
        (original / 'bin').mkdir(parents=True)
        (original / 'bin/clang-21').write_bytes(b'ORIGINAL FIXTURE; NEVER EXECUTED')
        (original / 'bin/clang-21').chmod(0o755)
        (original / 'share/wasi-sysroot/lib').mkdir(parents=True)
        (original / 'share/wasi-sysroot/lib/libc.a').write_bytes(b'UNCHANGED FIXTURE RUNTIME')
        (original / 'VERSION').write_bytes(('\n'.join(producer.OFFICIAL_VERSION) + '\n').encode())
        if os.name != 'nt':
            (original / 'bin/clang').symlink_to('clang-21')
        deadline = time.monotonic() + 30
        before = io.inventory(original, io.SDK_BYTES, deadline)
        shutil.copytree(original, products / 'toolchain', symlinks=True)
        (products / 'official-origin-VERSION').write_bytes((original / 'VERSION').read_bytes())
        for name, source in [('NOTICE', 'NOTICE'),
                ('LLVM-LICENSE.txt', 'tools/data/java-llvm-ssa/LICENSE.txt'),
                ('LLVM-PATCH.json', 'tools/data/java-llvm-ssa/patch.json')]:
            (products / name).write_bytes((patch.ROOT / source).read_bytes())
        # This carrier is synthetic: bind its copied current notices locally.
        # The real reader retains the immutable producer's notice identities.
        notices = mock.patch.object(inputs, 'NOTICES', {
            name: inputs.identity((products / name).read_bytes()) for name in inputs.NOTICES})
        notices.start()
        self.addCleanup(notices.stop)
        (products / 'toolchain/bin/clang-21').write_bytes(b'DERIVED FIXTURE; NEVER EXECUTED')
        library, clang_library = producer.LLVM_SONAME, producer.CLANG_SONAME
        (products / 'toolchain/lib').mkdir()
        (products / 'toolchain/lib' / library).write_bytes(b'DERIVED LIBRARY FIXTURE')
        (products / 'toolchain/lib' / clang_library).write_bytes(b'DERIVED CLANG LIBRARY FIXTURE')
        version = [producer.OFFICIAL_VERSION[0] + '-' + carrier.PROFILE,
                   *producer.OFFICIAL_VERSION[1:], 'lsf-llvm-patch-sha256: ' + patch.PATCH_SHA256]
        (products / 'toolchain/VERSION').write_bytes(('\n'.join(version) + '\n').encode())
        after = io.inventory(products / 'toolchain', io.PRODUCT_BYTES, deadline)
        distribution = carrier.create(directory, inputs.HEAD, deadline)
        xml = ET.Element('testsuites', tests='9', failures='0', disabled='0', errors='0')
        for name in patch.unit_cases():
            ET.SubElement(xml, 'testcase', classname='SSAUpdaterBulk', name=name.split('.', 1)[1],
                          status='run', result='completed')
        (directory / 'units.xml').write_bytes(ET.tostring(xml))
        xml = ET.Element('testsuites', tests='13', failures='0', errors='0', skipped='0')
        for row in results.selection()['wasmTests']:
            ET.SubElement(xml, 'testcase', name=Path(row['path']).name)
        (directory / 'lit.xml').write_bytes(ET.tostring(xml))
        # Synthetic IR exercises the actual bounded result decoder, not LLVM.
        raw = b'define void @fixture() {\nentry:\n call void @__wasm_setjmp()\n %x = catchswitch within none [] unwind to caller\n}\n'
        (directory / 'sjlj-through-wineh.ll').write_bytes(raw)
        obj = b'\0asm\x01\0\0\0'
        (directory / 'sjlj-through-wineh.o').write_bytes(obj)
        commands = []
        (directory / 'commands').mkdir()
        # Synthetic dynamic-section text exercises the real closed parser;
        # these tiny payload files are never executed or called compiled DSOs.
        loader = '(RUNPATH) Library runpath: [$ORIGIN/../lib]\n'
        elf_rows = {
            'compiled-clang-dynamic-dependencies': (
                f'(NEEDED) Shared library: [{library}]\n'
                f'(NEEDED) Shared library: [{clang_library}]\n' + loader).encode(),
            'compiled-llvm-dynamic-dependencies': (
                f'(SONAME) Library soname: [{library}]\n' + loader).encode(),
            'compiled-clang-cpp-dynamic-dependencies': (
                f'(SONAME) Library soname: [{clang_library}]\n'
                f'(NEEDED) Shared library: [{library}]\n' + loader).encode(),
        }
        for ordinal, stage in enumerate(inputs.STAGES):
            row = {'stage': stage, 'exitCode': 0, 'command': ['SYNTHETIC FIXTURE', stage]}
            for channel in ('stdout', 'stderr'):
                payload = (stage + ' fixture-only\n').encode() if channel == 'stdout' else b''
                if channel == 'stdout' and stage in elf_rows:
                    payload = elf_rows[stage]
                (directory / f'commands/{ordinal:02}-{stage}.{channel}.log').write_bytes(payload)
                row[channel] = inputs.identity(payload)
            commands.append(row)
        (directory / 'commands.json').write_bytes(carrier.encode(commands))
        original_source = {'files': patch.identities('original'), 'wholeTree': 'synthetic-before'}
        patched_source = {'files': patch.identities('modified'), 'wholeTree': 'synthetic-after'}
        patched = {'schemaVersion': patch.SCHEMA, 'llvmCommit': patch.LLVM,
                   'wasiSdkCommit': patch.SDK, 'patchSha256': patch.PATCH_SHA256,
                   'upstreamCommits': list(patch.UPSTREAM), 'before': patch.identities('original'),
                   'after': patch.identities('modified')}
        cross = results.cross_pass(raw)
        cross['object'] = inputs.identity(obj)
        cache = (b'CMAKE_GENERATOR:INTERNAL=Ninja\nLLVM_PARALLEL_COMPILE_JOBS:STRING=4\n'
                 b'LLVM_PARALLEL_LINK_JOBS:STRING=1\n')
        rules = b'pool compile_job_pool\n  depth = 4\npool link_job_pool\n  depth = 1\n'
        configuration = {'pools': {'compileJobs': 4, 'linkJobs': 1, 'cache': inputs.identity(cache)},
                         'files': {'retained-CMakeCache.txt': inputs.identity(cache),
                                   'retained-rules.ninja': inputs.identity(rules)}}
        (directory / 'retained-CMakeCache.txt').write_bytes(cache)
        (directory / 'retained-rules.ninja').write_bytes(rules)
        closure = {}
        for role, stage, member in [
                ('driver', 'compiled-clang-dynamic-dependencies', 'bin/clang-21'),
                ('llvm', 'compiled-llvm-dynamic-dependencies', 'lib/' + library),
                ('clang', 'compiled-clang-cpp-dynamic-dependencies', 'lib/' + clang_library)]:
            closure[role] = {**producer.elf_closure(elf_rows[stage], role),
                             'member': member, 'identity': after[member]}
        own = {'schemaVersion': 'latent.java.llvm-sjlj-producer.v1', 'status': 'passed',
               'profile': carrier.PROFILE, 'source': {'sourceCommit': inputs.HEAD, 'event': 'push',
                   'runId': str(inputs.RUN), 'runAttempt': str(inputs.ATTEMPT),
                   'workflowRef': inputs.REPOSITORY + '/' + inputs.WORKFLOW + '@refs/heads/' + inputs.BRANCH},
               'javaComponentQualification': False, 'javaRuntimeQualification': False,
               'aggregateSeconds': 5400, 'buildCommandSeconds': 4500,
               'buildJobs': 4, 'compileJobs': 4, 'linkJobs': 1,
               'litTimeoutSupport': {'name': 'psutil', 'version': '7.1.3', 'litTimeoutSeconds': 60,
                                    'support': 'pinned-lit-linux-psutil'},
               'buildPools': configuration['pools'],
               'initialConfiguration': configuration, 'retainedConfiguration': configuration,
               'earlyPackageProjection': {'existingEntries': 30, 'sdkEntries': 10,
                   'headerEntriesIncludingRoot': 3, 'fixedInstallAllowance': 32,
                   'fixedProductAllowance': 16, 'evidenceEntryAllowance': 512,
                   'projectedEntries': 604, 'entryLimit': 200000, 'buildMustBeRetired': True},
               'buildRetirement': {'child': 'build', 'before': {'entries': 12, 'logicalBytes': 100},
                   'removedDescendants': 12, 'removedRoot': True,
                   'afterOwned': {'entries': 100, 'logicalBytes': 1000}, 'liveCompilerChildren': 0,
                   'childObservationBasis': 'completed-original-process-owner', 'otherOwnedRootsRetired': False},
               'finalOwnedDisk': {'entries': 119, 'logicalBytes': 2000},
               'hostCapacity': {'status': 'admitted', 'reason': 'operational-preconditions-met',
                   'hardRssQuota': False, 'memoryFitQualified': False,
                   'minimumCpuMilli': 4000, 'effectiveCpuMilli': 4000,
                   'minimumTotalBytes': 12 * io.GIB, 'effectiveTotalBytes': 16 * io.GIB,
                   'minimumAvailableBytes': 10 * io.GIB, 'effectiveAvailableBytes': 12 * io.GIB},
               'llvmCommit': patch.LLVM,
               'sdkSourceCommit': patch.SDK, 'recipeInputs': recipe, 'patch': patched,
               'originalSource': original_source, 'patchedSource': patched_source, 'finalSource': patched_source,
               'tests': {'units': results.units((directory / 'units.xml').read_bytes()),
                         'originalSjLj': results.lit((directory / 'lit.xml').read_bytes()), 'crossPass': cross},
               'commands': len(commands), 'distribution': distribution,
               'products': {'baseSdk': before, 'derivedSdk': after,
                   'changedCompilerMembers': ['bin/clang-21'],
                   'addedCompilerMembers': ['lib/' + library, 'lib/' + clang_library],
                   'runtimeSysrootLldPreserved': True, 'customLlvmLibrary': library, 'customClangLibrary': clang_library,
                   'officialArchive': io.SDK_SOURCE,
                   'compiledElfClosure': closure,
                   'copyEntryProjection': {'existingEntries': 100, 'additionalEntries': 20,
                                           'projectedEntries': 120, 'entryLimit': 200000},
                   'retainedSourceNotices': inputs.NOTICES, 'originalVersion': producer.OFFICIAL_VERSION,
                   'derivedVersion': version}}
        (directory / 'source.json').write_bytes(carrier.encode({
            'before': original_source, 'patch': patched, 'after': patched_source}))
        (directory / 'result.json').write_bytes(carrier.encode(own))
        carrier.admit_upload(directory, inputs.HEAD, deadline)
        archive = root / 'synthetic-producer.zip'
        admission = json.loads((directory / 'upload-admission.json').read_bytes())
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as zipped:
            for name in [*admission['metadata'], carrier.ARCHIVE, 'upload-admission.json']:
                zipped.write(directory / name, name)
        pin = {'artifactId': 1, 'archiveBytes': archive.stat().st_size,
               'archiveSha256': patch.sha(archive.read_bytes()),
               'carrier': {k: distribution['archive'][k] for k in ('bytes', 'sha256')},
               'manifest': {k: distribution['manifest'][k] for k in ('bytes', 'sha256')},
               'originVersion': {k: before['VERSION'][k] for k in ('bytes', 'sha256')}}
        return archive, pin, own

    def test_unfilled_tuple_refuses_before_output_network_or_compiler(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {'RUNNER_TEMP': folder}), \
                mock.patch.object(inputs, 'QUALIFIED', None), \
                mock.patch.object(inputs.urllib.request, 'urlopen') as network, \
                mock.patch.object(inputs.urllib.request, 'build_opener') as api:
            with self.assertRaisesRegex(ValueError, 'qualified-tuple-unfilled'):
                inputs.prepare(time.monotonic() + 2)
            network.assert_not_called()
            api.assert_not_called()
            self.assertFalse((Path(folder) / 'java-llvm-public-inputs').exists())

    def test_default_official_gate_does_not_admit_derived_or_unknown_distribution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            compiler = Compiler.__new__(Compiler)
            compiler.wasi_sdk = root
            for version in [producer.OFFICIAL_VERSION,
                            [producer.OFFICIAL_VERSION[0] + '-' + carrier.PROFILE, *producer.OFFICIAL_VERSION[1:]],
                            ['31.0'], ['34.0'], ['29.0-unqualified']]:
                with self.subTest(version=version):
                    (root / 'VERSION').write_bytes(('\n'.join(version) + '\n').encode())
                    if version == producer.OFFICIAL_VERSION:
                        self.assertEqual(compiler._wasi_compiler_version(), '21.1.4-wasi-sdk')
                    else:
                        with self.assertRaisesRegex(ValueError, 'unreviewed WASI-SDK'):
                            compiler._wasi_compiler_version()
            # The withdrawn O0/Oz policies used normal VERSION files. Exercise
            # their real argv boundary rather than inventing version evidence.
            private = consumer.DerivedPublicCompiler.__new__(consumer.DerivedPublicCompiler)
            private.directory, private.sdk = root / 'compiler', patch.ROOT / 'sdk/java-guest'
            private.paths = {'clang': root / 'bin/clang'}
            private._derived = mock.Mock(deadline=time.monotonic() + 5)
            private.deadline = private._derived.deadline
            original = consumer.public_wineh.expected_command(private, root)
            for optimizer in ('-O0', '-Oz', '-fno-inline'):
                command = [optimizer if item == '-O2' else item for item in original]
                with self.subTest(optimizer=optimizer), mock.patch.object(Compiler, 'run') as owner:
                    with self.assertRaisesRegex(ValueError, 'public-command'):
                        private.run('c-to-wasm', 'clang', *command[1:])
                    owner.assert_not_called()

    def test_small_actual_carrier_extraction_preserves_members_and_detects_real_material_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, pin, own = self.fixture(root)
            target = root / 'java-llvm-public-inputs'
            target.mkdir()
            with mock.patch.object(inputs, 'QUALIFIED', pin), mock.patch.dict(os.environ, {'RUNNER_TEMP': str(root)}):
                admitted = inputs.decode(archive, target, time.monotonic() + 30)
                admitted.recheck(admitted.sdk)
                self.assertEqual((admitted.sdk / 'share/wasi-sysroot/lib/libc.a').read_bytes(), b'UNCHANGED FIXTURE RUNTIME')
                if os.name != 'nt':
                    self.assertEqual((admitted.sdk / 'bin/clang-21').stat().st_mode & 0o777, 0o755)
                    self.assertTrue((admitted.sdk / 'bin/clang').is_symlink())
                    self.assertEqual(os.readlink(admitted.sdk / 'bin/clang'), 'clang-21')
                compiler = consumer.DerivedPublicCompiler.__new__(consumer.DerivedPublicCompiler)
                compiler._derived, compiler.wasi_sdk = admitted, admitted.sdk
                self.assertEqual(compiler._wasi_compiler_version(), '21.1.4' + producer.SUFFIX)
                # Actual derived __init__/run/normal-owner code at the delay
                # boundary; no model of its arithmetic and no version process.
                clock, observed, original_deadline = [90.0], [], admitted.deadline
                admitted.deadline = 100.0
                def delayed_base(instance, directory, wasi_sdk, **options):
                    observed.append(instance)
                    clock[0] = 101.0
                    instance.deadline = clock[0] + options['timeout']
                    instance.run('clang-version', 'clang', '--version')
                with mock.patch.object(consumer.time, 'monotonic', side_effect=lambda: clock[0]), \
                        mock.patch.object(Compiler, '__init__', delayed_base), \
                        mock.patch('tools.java_guest.compiler.run_bounded_result') as process:
                    with self.assertRaisesRegex(ValueError, 'Java build deadline exceeded'):
                        consumer.DerivedPublicCompiler(root / 'expired-compiler', admitted.sdk, admitted=admitted)
                    process.assert_not_called()
                self.assertEqual(observed[0].deadline, 100.0)
                admitted.deadline = original_deadline
                for name in ('bin/clang-21', 'lib/' + own['products']['customLlvmLibrary'],
                             'lib/' + own['products']['customClangLibrary'],
                             'share/wasi-sysroot/lib/libc.a', 'VERSION'):
                    with self.subTest(material=name):
                        path = admitted.sdk / name
                        original = path.read_bytes()
                        path.write_bytes(original + b'changed')
                        with self.assertRaisesRegex(ValueError, 'sdk-changed'):
                            admitted.recheck(admitted.sdk)
                        path.write_bytes(original)
                        admitted.recheck(admitted.sdk)
                with self.assertRaisesRegex(ValueError, 'fixed-sdk-root'):
                    admitted.recheck(root / 'arbitrary-sdk')

    def test_actual_archive_hash_and_metadata_gate_refuse_before_product_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            archive, pin, own = self.fixture(root)
            inputs.producer_settings(own)
            with zipfile.ZipFile(archive) as zipped:
                index = {row.filename: row for row in zipped.infolist()}
                inputs.delivery_evidence(zipped, index, own)
                for mutate, reason in [
                        (lambda value: value['retainedConfiguration']['files']['retained-rules.ninja'].update(sha256='0' * 64), 'configuration'),
                        (lambda value: value['buildRetirement'].update(liveCompilerChildren=True), 'delivery-retirement'),
                        (lambda value: value['buildRetirement'].update(removedDescendants=11), 'delivery-retired-count'),
                        (lambda value: value['products']['copyEntryProjection'].update(projectedEntries=200001), 'delivery-copy-projection'),
                        (lambda value: value['finalOwnedDisk'].update(entries=121), 'delivery-copy-projection'),
                        (lambda value: value['products']['compiledElfClosure'].pop('clang'), 'delivery-two-dso-closure'),
                        (lambda value: value['products']['compiledElfClosure']['clang'].update(member='lib/other.so'), 'delivery-two-dso-binding')]:
                    changed = copy.deepcopy(own)
                    mutate(changed)
                    with self.subTest(deliveryMutation=reason), self.assertRaisesRegex(ValueError, reason):
                        inputs.delivery_evidence(zipped, index, changed)
            # Call the real settings gate used by selected(), without modeling
            # its predicates or presenting synthetic rows as hosted evidence.
            for field, value, reason in [
                ('buildJobs', 2, 'build-settings'), ('buildCommandSeconds', 3600, 'build-settings'),
                ('linkJobs', True, 'build-settings'),
                ('litTimeoutSupport', {**own['litTimeoutSupport'], 'version': '7.1.2'}, 'lit-timeout'),
                ('buildPools', {**own['buildPools'], 'linkJobs': 4}, 'build-pools'),
                ('hostCapacity', {**own['hostCapacity'], 'effectiveAvailableBytes': 9 * io.GIB}, 'host-capacity'),
                ('hostCapacity', {**own['hostCapacity'], 'memoryFitQualified': True}, 'host-capacity'),
                ('recipeInputs', {k: v for k, v in own['recipeInputs'].items()
                                  if not k.endswith('/requirements.lock')}, 'producer-recipe'),
                ('recipeInputs', {**own['recipeInputs'],
                                  'tools/data/java-llvm-ssa/requirements.lock':
                                  {'bytes': 174, 'sha256': '0' * 64}}, 'producer-recipe'),
            ]:
                with self.subTest(producerMutation=field), self.assertRaisesRegex(ValueError, reason):
                    inputs.producer_settings({**own, field: value})
            target = root / 'uncreated-products'
            target.mkdir()
            with mock.patch.object(inputs, 'QUALIFIED', {**pin, 'archiveSha256': '0' * 64}):
                with self.assertRaisesRegex(ValueError, 'archive-before-parse'):
                    inputs.decode(archive, target, time.monotonic() + 5)
            self.assertEqual(list(target.iterdir()), [])
            for variant in ('unknown', 'traversal', 'changed-manifest'):
                with self.subTest(archiveMutation=variant):
                    mutant = root / (variant + '.zip')
                    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(mutant, 'w') as changed:
                        for info in original.infolist():
                            raw = original.read(info)
                            if variant == 'changed-manifest' and info.filename == carrier.MANIFEST:
                                raw += b'changed'
                            changed.writestr(info, raw)
                        if variant != 'changed-manifest':
                            changed.writestr('unknown' if variant == 'unknown' else '../escape', b'not admitted')
                    # Bind the actual mutant ZIP to reach the inner closure
                    # checks, instead of merely exercising the outer hash gate.
                    altered_pin = {**pin, 'archiveBytes': mutant.stat().st_size,
                                   'archiveSha256': patch.sha(mutant.read_bytes())}
                    with mock.patch.object(inputs, 'QUALIFIED', altered_pin):
                        with self.assertRaises(ValueError):
                            inputs.decode(mutant, target, time.monotonic() + 5)
                    self.assertEqual(list(target.iterdir()), [])
                    self.assertFalse((root / 'escape').exists())
            run = {'id': inputs.RUN, 'run_attempt': 1, 'head_sha': inputs.HEAD,
                   'head_branch': inputs.BRANCH, 'path': inputs.WORKFLOW, 'event': 'push',
                   'status': 'completed', 'conclusion': 'success', 'head_commit': {'tree_id': inputs.TREE}}
            job = {'id': inputs.JOB, 'run_id': inputs.RUN, 'head_sha': inputs.HEAD,
                   'name': 'Build and test one source-bound LLVM 21 compiler', 'status': 'completed',
                   'conclusion': 'success', 'steps': [{'status': 'completed', 'conclusion': 'success'}]}
            artifact = {'id': 1, 'expired': False, 'name': 'java-llvm-ssa-producer-' + inputs.HEAD,
                        'workflow_run': {'id': inputs.RUN, 'head_sha': inputs.HEAD},
                        'size_in_bytes': pin['archiveBytes'], 'digest': 'sha256:' + pin['archiveSha256']}
            with mock.patch.object(inputs, 'QUALIFIED', pin):
                with zipfile.ZipFile(archive) as zipped:
                    manifest = json.loads(zipped.read(carrier.MANIFEST))
                altered_origin = copy.deepcopy(manifest)
                altered_origin['members']['official-origin-VERSION']['sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'origin-version'):
                    inputs.verify_runtime_preservation(own, altered_origin)
                inputs.metadata(run, job, artifact)
                for key, value in [('event', 'workflow_dispatch'), ('head_sha', '0' * 40),
                                   ('conclusion', 'failure'), ('run_attempt', 2)]:
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'successful-producer'):
                        inputs.metadata({**run, key: value}, job, artifact)
                with self.assertRaisesRegex(ValueError, 'exact-artifact'):
                    inputs.metadata(run, job, {**artifact, 'expired': True})


if __name__ == '__main__':
    unittest.main()

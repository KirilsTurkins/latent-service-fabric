"""Three read-only-prefix observations of one original failed C guest; never qualify17."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_thread_prefix_inputs as inputs, c_thread_runtime_node as original
from tools import host_codec_native_products as native
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.c_guest.threading import PROFILE
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS, integer
from tools.qualify_c_thread_runtime import materials, native_evidence, build_evidence
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy, sample, selected_revision, start_call
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.sdk_provider_scenario import start_provider

HELPERS = ('tools/diagnose_c_thread_prefix.py', 'tools/c_thread_prefix_inputs.py',
    '.github/workflows/c-thread-prefix-diagnostic.yml')
MODES = ('application-error', 'c11', 'pthread')


def source_inputs():
    return {**materials(), **{name: file_identity(ROOT/name) for name in HELPERS}}


def audit(client, started, output, activation):
    pages, token = [], None
    for index in range(4):
        args = ('audit', 'query', '--scope', 'tenant', '--page-size', '64',
            '--from-unix-millis', str(max(0, started-1)))
        if token is not None: args += ('--page-token', token)
        page = client.call(*args); pages.append(page)
        write_json(output/f'audit-{activation}-{index}.json', page)
        token = page['data']['page']['nextPageToken']
        if token is None: break
    return pages, token


def retirement(client, probe, target, output, activation):
    physical = sample(client, probe, 'after-'+activation, 1)
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    value = {'physical': physical, 'providerUsage': usage}
    write_json(output/('retirement-'+activation+'.json'), value)
    topology = physical['inventory']['topology']
    entries = {row['name']: row for row in topology['entries']}
    require(topology['available'] is True and topology['complete'] is True
        and len(entries) == len(topology['entries'])
        and all(integer(entries[name]['activeCount']) == 0 for name in original.LIVE),
        'c-prefix-all-five-real-physical-owners-retired')
    counters = usage['nodeUsage']
    require(usage['nextPageToken'] is None and counters['scope'] == 'node'
        and type(counters['unavailable']) is list and counters['unavailable'] == []
        and all(integer(counters['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
        'c-prefix-all-eighteen-available-provider-counters-idle')
    return file_identity(output/('retirement-'+activation+'.json'))


def observe(client, node, probe, target, output, mode):
    activation = 'c-prefix-' + mode
    revision = selected_revision(client, target)
    process = start_call(client, target, original.SERVICE, 'greet', [mode], activation)
    primary = False
    try:
        row = original.finish_call(client, process)
        # Retain actual public result, existing audit and real physical/provider
        # observations BEFORE testing any result or native/guest owner oracle.
        write_json(output/('invocation-'+activation+'.json'), row)
        pages, remaining = audit(client, process.authoring_started_unix_millis, output, activation)
        retired = retirement(client, probe, target, output, activation)
        require(remaining is None, 'c-prefix-bounded-complete-audit-pages')
        node.drain()
        require(len(node.buffers[1]) <= 262144, 'c-prefix-normal-stderr-bound')
        (output/('normal-stderr-'+activation+'.txt')).write_bytes(bytes(node.buffers[1]))
        response = row['response']
        require(row['processReaped'] is True and response['outcomeKnown'] is True
            and response['requestDispatched'] is True
            and response['data']['resolvedRevision'] == revision, 'c-prefix-known-current-reaped-outcome')
        value = response['data']['consumption']
        require(0 < integer(value['cpuFuel']) <= target['budget']['cpuFuel']
            and 0 < integer(value['peakMemoryBytes']) <= target['budget']['memoryBytes']
            and all(integer(value[name]) == 0 for name in ('outboundRequests', 'effectCount',
                'childCalls', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes', 'logBytes')),
            'c-prefix-original-envelope-no-other-effects')
        return {'mode': mode, 'invocation': file_identity(output/('invocation-'+activation+'.json')),
            'retirement': retired, 'auditPages': len(pages), 'exitCode': row['exitCode'],
            'decoded': row['decoded'], 'error': response['error'],
            'precisePrivateTrapObserved': False, 'instructionCauseClaimed': False,
            'qualification': False}
    except BaseException:
        primary = True
        try: original.retain_partial(process, output, activation)
        except BaseException: pass
        raise
    finally:
        original.close_call(process, primary_failure=primary)


def run(prepared, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
        'c-prefix-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and output not in ROOT.parents and ROOT not in output.parents,
        'c-prefix-output-outside-checkout')
    output = fresh(output);before = source_inputs()
    origin, source, tools = native_evidence(native, prepared)
    commands = Commands(ROOT, fresh(output/'commands'), build_environment(output), deadline_seconds=600, command_seconds=90)
    record = {'schemaVersion': 'latent.c.thread-prefix.diagnostic.v1', 'status': 'incomplete',
        'qualification': False, 'diagnosticOnly': True, 'full17ProgrammeQualified': False,
        'nativeProductsRebuilt': False, 'guestRecompiled': False, 'normalPackageEnvelopeRecreated': False,
        'materials': before,
        'nativeSource': source, 'nativeOrigin': origin, 'outcomes': []}
    try:
        artifact, restoration = inputs.acquire(output/'original')
        record['restoration'] = restoration
        original_build = read_json(artifact.parent/'FAILED.json')['build']
        package_inputs = read_json(artifact/'package-inputs.json')
        # Recreate only the normal package envelope. The compiler observation,
        # source/recipe receipts and original component bytes are not rewritten.
        commands.run('normal-package-original-component', tools['package'], 'build', artifact/'package-source.json',
            artifact, artifact/'package', *restoration['packagingArguments'])
        commands.run('inspect-original-component-package', tools['package'], 'inspect', artifact/'package',
            *restoration['packagingArguments'])
        record['normalPackageEnvelopeRecreated'] = True
        signed = output/'signed'
        commands.run('normal-sign-original-component', tools['capsule_authoring'], 'demo-sign', signed, artifact)
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-prefix-') as temp, original.owned_cleanup(record) as cleanup:
            work = Path(temp)
            for name in ('client','node','peer'): (work/name).mkdir(mode=0o700)
            client = RecordingClient(tools['latent'], work/'client', cancellation,
                min(commands.deadline,time.monotonic()+240), evidence=output/'controls')
            peer, port = start_provider(client,work/'peer',maximum_seconds=240);cleanup.callback(peer.close)
            config, settings = configure(work/'node',signed,port,language='c')
            original.configure(settings,read_json(artifact/'capsule.json'))
            config.write_bytes((json.dumps(settings,sort_keys=True,separators=(',',':'))+'\n').encode())
            record['configuration'] = settings
            node = connect(client,tools['latentd'],work/'node',config,'examples',0);cleanup.callback(node.close)
            record['startup'] = node.startup_record;probe = Probe(node,file_identity(tools['latentd']))
            release = signed/original.SERVICE
            published = client.call('release','publish-package',release/'package','--evidence',release/'evidence/index.json',
                '--operation-id','c-prefix-publish','--expected-generation','0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest']==inputs.COMPONENT['sha256'],
                'c-prefix-exact-original-component-publication')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client,release/'deployment.json',publication)
            grants = original.install(client,node,target)
            target = deploy(client,release/'deployment.json',publication,generation=str(target['generation']),grants=grants)
            for mode in MODES:
                record['outcomes'].append(observe(client,node,probe,target,output,mode))
                write_json(output/('progress-'+mode+'.json'),record)
            delete_all(client,[target['name']]);record['afterDelete']=sample(client,probe,'c-prefix-after-delete',0)
            stop(client,node);record['nodeShutdown']=stopped_record(node)
            record['peerShutdown']=stop_observation_peer(peer)
            require(record['nodeShutdown']['reaped'] is True and record['nodeShutdown']['record']['clean'] is True,
                'c-prefix-clean-reaped-node')
            cancellation.check()
        require(source_inputs()==before and native_evidence(native,prepared)==(origin,source,tools)
            and build_evidence(artifact,(artifact/'source-inputs.json').read_bytes())==original_build
            and read_json(artifact/'package-inputs.json')==package_inputs
            and len(record['outcomes'])==3 and client.calls<=384 and time.monotonic()<commands.deadline,
            'c-prefix-unchanged-original-source-component-provenance-and-bounds')
        record['rootPrefixControlPassed'] = (record['outcomes'][0]['exitCode'] == 3
            and record['outcomes'][0]['decoded'] == [{'err': 'application-error'}])
        require(record['rootPrefixControlPassed'], 'c-prefix-original-root-initialization-control')
        record.update(status='observed',commands=commands.records)
        write_json(output/'diagnostic.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',errorCategory=type(error).__name__,commands=commands.records)
        try: write_json(output/'FAILED.json',record)
        except BaseException: pass
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();value=run(args.prepared,args.output)
    print(json.dumps({'status':value['status'],'qualification':False,'attempts':len(value['outcomes'])}))

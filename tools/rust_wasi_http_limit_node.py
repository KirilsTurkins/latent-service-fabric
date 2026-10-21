"""Nine isolated limits attempts on the original ordinary-client component."""
from __future__ import annotations

import copy
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

from tools import rust_wasi_http_runtime_node as original
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, selected_revision
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.standard_http.peer import Peer

MATERIALS = ('tools/rust_wasi_http_limit_node.py', *original.MATERIALS)
PHASES = ('baseline', 'task-one', 'timer-one', 'memory-three-mib')
MEMORY_COMPONENT = {'sha256': 'sha256:51c0ff8e1cd93ae504a8f14d861fb8ac862b4cf6bdab2d22074183c1e692eb4f', 'bytes': 934498}
NORMAL_BUDGET = {'blobReadBytes': 0, 'blobWriteBytes': 0, 'childCalls': 0,
    'cpuFuel': 1_000_000_000, 'effectCount': 0, 'logBytes': 0, 'memoryBytes': 16 * 1024**2,
    'outboundRequests': 8, 'stateReadBytes': 0, 'stateWriteBytes': 0, 'wallTimeLimitMillis': 5000}
MEMORY_CONTEXT = {'component': MEMORY_COMPONENT,
    # These three main cores are instantiated by runtime/application/root in the
    # exact authenticated component. The digest binds the complete instance graph.
    'instantiatedMainCoreOrdinals': [0, 3, 6], 'minimumPages': [17, 19, 17],
    'minimumInstantiatedLinearMemoryBytes': 53 * 65536,
    'definitionSumAloneProvesInstantiation': False, 'measuredRssClaimed': False}


def limits_configuration(value, phase):
    """Change exactly one operator owner ceiling; memory is per invocation."""
    require(phase in PHASES and value['providers']['activationRuntime']['limits'] == original.RUNTIME_LIMITS,
            'rust-limit-original-installed-ceilings')
    result = copy.deepcopy(value)
    if phase in ('task-one', 'timer-one'):
        key = 'tasks' if phase == 'task-one' else 'timers'
        result['providers']['activationRuntime']['limits'][key] = 1
    return result


def owned_cleanup(action, label, observations):
    def close():
        primary = sys.exc_info()[0] is not None
        try:
            action()
        except BaseException:
            if not primary:
                raise
            observations.append({'owner': label, 'cleanupRefused': True, 'primaryPreserved': True})
    return close


def memory_outcome(row, revision, budget):
    response = row['response']; data = response['data']; error = response.get('error', {})
    require(row['exitCode'] == 4 and row['decoded'] is None and row['processReaped'] is True
            and response['outcomeKnown'] is response['requestDispatched'] is True
            and response['category'] == 'platform-failure' and data['resolvedRevision'] == revision
            and data['terminalState'] == 'resource_exhausted' and error.get('code') == 'resource-exhausted',
            'rust-limit-exact-memory-public-terminal')
    details = error['details']
    require(type(details) is list and len(details) <= 16
            and sum(d.get('kind') == 'activation.memory-exhausted' for d in details) == 1,
            'rust-limit-typed-memory-producer-detail-required')
    consumption = data['consumption']
    require(type(consumption['outboundRequests']) is int and consumption['outboundRequests'] == 0
            and original.unsigned(consumption['peakMemoryBytes']) <= budget['memoryBytes']
            and original.unsigned(consumption['cpuFuel']) <= budget['cpuFuel'],
            'rust-limit-memory-original-budget-no-contact')
    return {'producerDetail': 'activation.memory-exhausted', 'genericResourceErrorAccepted': False,
            'requestedMemoryBytes': budget['memoryBytes'], 'guestExecutionClaimed': False}


def memory_selection(budget):
    require(budget == NORMAL_BUDGET and all(type(v) is int for v in budget.values()),
        'rust-limit-memory-original-complete-budget')
    return {**budget, 'memoryBytes': 3 * 1024**2}


def memory_differential_outcome(row, revision, budget, context):
    """A fixed-component differential; the generic public error is insufficient."""
    require(json.dumps(context, sort_keys=True) == json.dumps(MEMORY_CONTEXT, sort_keys=True)
        and budget == memory_selection(NORMAL_BUDGET) and all(type(v) is int for v in budget.values())
        and revision['releaseDigest'] == MEMORY_COMPONENT['sha256'],
        'rust-limit-fixed-component-and-only-memory-request-differential')
    response = row['response']; data = response['data']; error = response['error']
    require(type(row['exitCode']) is int and row['exitCode'] == 4 and row['decoded'] is None
        and row['processReaped'] is True and response['outcomeKnown'] is response['requestDispatched'] is True
        and response['category'] == 'platform-failure' and data['resolvedRevision'] == revision
        and data['terminalState'] == 'resource_exhausted'
        and error == {'code': 'resource-exhausted', 'details': [],
            'message': 'The platform reported a failure.', 'retryable': False},
        'rust-limit-original-public-memory-projection')
    consumed = data['consumption']
    require(all(type(consumed[k]) is int and consumed[k] == 0
            for k in ('outboundRequests', 'effectCount', 'childCalls'))
        and all(original.unsigned(consumed[k]) == 0 for k in
            ('logBytes', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes'))
        and 0 < original.unsigned(consumed['cpuFuel']) < budget['cpuFuel']
        and 0 < original.unsigned(consumed['peakMemoryBytes']) <= budget['memoryBytes'],
        'rust-limit-memory-no-effects-and-unexhausted-fuel')
    return {'proofKind': 'fixed-instantiated-component-single-memory-request-differential',
        'requestedMemoryBytes': budget['memoryBytes'],
        'minimumInstantiatedLinearMemoryBytes': context['minimumInstantiatedLinearMemoryBytes'],
        'publicGenericErrorAloneProvesMemory': False, 'internalInstructionOrAllocationSiteProved': False,
        'transportTypedDetailObserved': False, 'transportDetailOmittedByOriginalProjection': True,
        'matchedSameCellFreshRequired': True, 'status': 'awaiting-matched-fresh'}


def complete_memory_differential(lower, fresh_result):
    require(memory_differential_outcome(lower['invocation'], lower['selectedRevision'],
            lower['budget'], MEMORY_CONTEXT) == lower['diagnostic']
        and fresh_result['budget'] == NORMAL_BUDGET
        and all(type(v) is int for v in fresh_result['budget'].values())
        and fresh_result['selectedRevision']['releaseDigest'] == MEMORY_COMPONENT['sha256']
        and fresh_result['case'] == 'fresh-memory-three-mib' and fresh_result['client'] == 'golem',
        'rust-limit-mandatory-original-budget-opposite-fresh')
    original.outcome(fresh_result['invocation'], original.cases()[0], 'golem',
        fresh_result['selectedRevision'], fresh_result['budget'])
    return {**lower['diagnostic'], 'status': 'passed', 'matchedSameCellFreshObserved': True,
        'upperRequestedMemoryBytes': fresh_result['budget']['memoryBytes']}


def task_outcome(row, revision, budget):
    spec = next(s for s in original.cases() if s[0] == 'resource-capacity')
    evidence = original.outcome(row, spec, 'waki', revision, budget)
    require(evidence['observedAcceptedResponses'] == 1, 'rust-limit-exact-one-retained-task-response')
    return {'acceptedResponses': 1, 'typedPublicError': evidence['publicError'],
            'changedCeiling': {'tasks': 1}, 'otherCeilingsChanged': False,
            'taskSource': 'sdk/wasi-http-runtime/state.rs::Exchange::admit',
            'publicErrorAloneProvesOwnerKind': False}


def timer_outcome(row, revision, budget, positive):
    response = row['response']; data = response['data']
    require(row['exitCode'] == 4 and row['decoded'] is None and row['processReaped'] is True
            and response['outcomeKnown'] is response['requestDispatched'] is True
            and response['category'] == 'platform-failure' and data['resolvedRevision'] == revision
            and data['terminalState'] == 'guest_trap' and response['error']['code'] == 'guest-trap'
            and response['error']['details'] == [
                {'fields': {'code': 'guest-trap'}, 'kind': 'activation.guest-trap'},
                {'fields': {'kind': 'unreachable-code'}, 'kind': 'activation.guest-trap-kind'}],
            'rust-limit-exact-timer-pressure-trap')
    consumption = data['consumption']
    require(consumption['outboundRequests'] == 2
            and 0 < original.unsigned(consumption['cpuFuel']) <= budget['cpuFuel']
            and 0 < original.unsigned(consumption['peakMemoryBytes']) <= budget['memoryBytes']
            and type(positive['transitiveTimer']['waitPending']['timers']) is int
            and positive['transitiveTimer']['waitPending']['timers'] == 1,
            'rust-limit-one-live-timer-before-second-start')
    return {'changedCeiling': {'timers': 1}, 'observedOutboundStarts': 2,
            'realFirstTimerPending': True, 'trapInstructionProved': False,
            'genericTrapAloneProvesOwnerKind': False}


def baseline_timer(stderr):
    """Ordinary Rust drain settles owners; it does not call activation.close."""
    require(type(stderr) is bytes and len(stderr) <= original.MAXIMUM_STDERR,
        'rust-limit-bounded-baseline-timer-source')
    observed = original.timer_observer.observe(stderr)
    require(observed['status'] == 'observed' and observed['invalidMarkerCount'] == 0
        and not observed['overflow'], 'rust-limit-valid-baseline-timer-records')
    rows = observed['records']
    sequences = [int(line.split(b'|')[3]) for line in stderr.splitlines()
        if line.startswith(original.TIMER_PREFIX)]
    require(sequences == list(range(1, len(rows) + 1))
        and all(row['mode'] == 'pending' for row in rows), 'rust-limit-current-baseline-timer-sequence')
    pending = [row for row in rows if row['event'] == 'wait-pending'
        and all(1 <= row[key] <= original.RUNTIME_LIMITS[key] for key in ('tasks', 'waits', 'timers'))]
    closes = [row for row in rows if row['event'] == 'root-close']
    require(pending and len(closes) <= 1
        and all(row['sequence'] > pending[-1]['sequence'] for row in closes),
        'rust-limit-live-baseline-timer-no-stale-close')
    return {'nativeRecords': observed, 'waitPending': pending[-1],
        'guestCloseStatus': 'observed' if closes else 'not-observed',
        'guestCloseSynthesized': False, 'forcedHostTermination': False,
        'drainContract': 'compiler-private-drain-retired-owner-settlement',
        'physicalRetirementProvenByMarker': False}


def boundary_call(client, node, target, peers, tenant, phase, probe, output, memory_context):
    memory = phase == 'memory-three-mib'; timer = phase == 'timer-one'
    library = 'golem' if timer else 'waki'
    label = 'node-stop-pending' if timer else phase
    chosen = copy.deepcopy(target)
    if memory:
        chosen['budget'] = memory_selection(target['budget'])
        write_json(output / 'memory-request-selection.json', {'original': target['budget'],
            'selected': chosen['budget'], 'context': memory_context, 'onlyMemoryBytesChanged': True})
    path = 'domain-json' if memory else 'pending-headers'
    mode = 'json' if memory else 'capacity'
    endpoint = peers[tenant].url(path)
    before = {t: p.observation() for t, p in peers.items()}
    revision = selected_revision(client, target)
    process = original.start_call(client, chosen, 'greeting', 'greet',
        ['alpha|' + library + '|' + mode + '|' + endpoint], label)
    primary = False; positive = None; released = False
    try:
        expires = min(client.deadline, time.monotonic() + 10)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'rust-limit-original-call-deadline')
            process.drain(); node.drain()
            for peer in peers.values():
                peer.poll(.002)
                require(peer.observation()['failure'] is None, 'rust-limit-controlled-peer-failed')
            gates = [g for g in peers[tenant].gates() if g.request > before[tenant]['acceptedConnections']]
            if not memory and not released and gates:
                require(len(gates) == 1 and gates[0].phase == 'headers', 'rust-limit-first-ordinary-headers-gate')
                witness = original.golem_timer_pending(bytes(node.buffers[1]), 'pending') if timer else None
                if timer and witness is None: continue
                positive = {'physicalAndProvider': original.positive_pending(client, probe, target),
                    'transitiveTimer': witness, 'gate': {'request': gates[0].request, 'phase': 'headers'}}
                write_json(output / ('pending-' + phase + '.json'), positive)
                require(not process.owner.exited(), 'rust-limit-root-live-at-positive-barrier')
                peers[tenant].release(gates[0]); released = True
        row = original.finish_call(client, process)
    except BaseException:
        primary = True
        original.retain_after_failure(process, node, output, phase)
        raise
    finally:
        original.close_call(process, primary_failure=primary)
    write_json(output / ('invocation-' + phase + '.json'), row)
    terminal_timer = None
    if timer:
        raw = original.retain_terminal_timer(node, output, phase)
        terminal_timer = original.timer_observer.observe(raw)
        require(terminal_timer['invalidMarkerCount'] == 0 and not terminal_timer['overflow'],
                'rust-limit-terminal-timer-records-valid')
    for _ in range(64):
        for peer in peers.values(): peer.poll(.002)
        if all(p.observation()['openConnections'] == 0 for p in peers.values()): break
    after = {t: p.observation() for t, p in peers.items()}
    original.retain_peer_observations(output, phase, before, after)
    # Retire and retain before the new limit-specific oracle may refuse.
    retired = original.retire(client, probe, target, output, phase)
    require(memory or positive is not None and released, 'rust-limit-positive-first-request-required')
    diagnostic = (memory_differential_outcome(row, revision, chosen['budget'], memory_context) if memory else
        timer_outcome(row, revision, chosen['budget'], positive) if timer else
        task_outcome(row, revision, chosen['budget']))
    for other in peers:
        change = original.delta(before[other], after[other])
        require(after[other]['openConnections'] == 0, 'rust-limit-all-real-peer-connections-closed')
        if other != tenant or memory:
            original.require_zero_contact(before[other], after[other])
        else:
            new = after[other]['requests'][before[other]['acceptedConnections']:]
            maximum = 2 if timer else 1
            require(1 <= change['acceptedConnections'] <= maximum
                    and 1 <= change['startedRequests'] <= change['acceptedConnections']
                    and change['completedResponseWrites'] == 1, 'rust-limit-source-bounded-requests-after-first-release')
            parsed = [r for r in new if 'vector' in r]
            require(all(r['vector'] == 'pending-headers' and r['method'] == 'GET'
                    and r['bodyBytes'] == 0 and r['authorizationPresent'] is True
                    and r['cookiePresent'] is r['proxyAuthorizationPresent'] is False
                    and r['state'] == 'closed' for r in parsed), 'rust-limit-exact-controlled-pressure-peer-requests')
            for r in new:
                if 'vector' not in r: original.closed_before_request(r)
    result = {'phase': phase, 'invocation': row, 'selectedRevision': revision,
        'budget': chosen['budget'], 'positive': positive, 'diagnostic': diagnostic,
        'terminalTimer': terminal_timer, 'guestCloseSynthesized': False,
        'before': before, 'after': after, 'retirement': retired}
    write_json(output / ('case-' + phase + '.json'), result)
    return result


def run(artifact, native, output, *, deadline, memory_context):
    output = fresh(output)
    names = ('component.wasm','BUILD-COMPLETE.json','source-inputs.json','recipe-inputs.json',
        'build-observation.json','capsule.json','package-source.json','rust-http-runtime.json')
    identities = {n: file_identity(artifact / n) for n in names}
    require(identities['component.wasm'] == MEMORY_COMPONENT and memory_context == MEMORY_CONTEXT,
        'rust-limit-original-whole-instantiated-component-identity')
    record = {'schemaVersion':'latent.rust.wasi-http.limits.v1','status':'incomplete',
        'fullTicketQualification':False,'original':identities,'attempts':[],'phases':[],'cleanupRefusals':[]}
    signed = output / 'releases'
    stage = 'normal-unchanged-component-signing'
    try:
        result = run_bounded_result([str(native['capsule_authoring']),'demo-sign-neutral-resources',str(signed),str(artifact)],
            output, build_environment(output), min(30, deadline-time.monotonic()), 65536)
        require(result.returncode == 0, 'rust-limit-normal-signing')
        record['signing'] = original.checked_signing(artifact, signed, identities)
        for phase in PHASES:
            stage = phase; phase_output = output / phase; phase_output.mkdir(mode=0o700)
            with tempfile.TemporaryDirectory(prefix='lsf-rust-http-limit-') as temporary, owned_cancellation() as cancellation, ExitStack() as cleanup:
                work = Path(temporary)
                for name in ('node','examples','peers'): (work/name).mkdir(mode=0o700)
                peers = {}; credentials = {}; private_values = []
                for tenant in original.TENANTS:
                    directory=work/'peers'/tenant;directory.mkdir(mode=0o700)
                    secret=('Bearer '+secrets.token_hex(32)).encode();private_values.append(secret)
                    path=directory/'authorization';path.write_bytes(secret);path.chmod(0o600);credentials[tenant]=path
                    peers[tenant]=Peer(secret,maximum_seconds=240)
                    cleanup.callback(owned_cleanup(peers[tenant].close,'peer-'+tenant,record['cleanupRefusals']))
                client=RecordingClient(native['latent'],work/'examples',cancellation,min(deadline,time.monotonic()+220),
                    evidence=phase_output/'examples-controls')
                config=original.configuration(work/'node',signed,peers,credentials)
                before_config=read_json(config);before_identity=file_identity(config)
                selected=limits_configuration(before_config,phase)
                restored=copy.deepcopy(selected)
                if phase in ('task-one','timer-one'):
                    key='tasks' if phase=='task-one' else 'timers'
                    require(type(selected['providers']['activationRuntime']['limits'][key]) is int
                        and selected['providers']['activationRuntime']['limits'][key]==1,'rust-limit-selected-ceiling-one')
                    restored['providers']['activationRuntime']['limits'][key]=original.RUNTIME_LIMITS[key]
                require(restored==before_config,'rust-limit-all-other-configuration-byte-values-preserved')
                config.write_text(json.dumps(selected,indent=2)+'\n',encoding='utf-8')
                write_json(phase_output/'configuration-selection.json',{'phase':phase,
                    'originalLimits':original.RUNTIME_LIMITS,'selectedLimits':selected['providers']['activationRuntime']['limits'],
                    'before':before_identity,'selected':file_identity(config),'onlyOneOwnerCeilingChanged':phase in ('task-one','timer-one')})
                client.environment[original.TIMER_ENVIRONMENT]='1'
                node=connect(client,native['latentd'],work/'node',config,'examples',1)
                cleanup.callback(owned_cleanup(node.close,'node',record['cleanupRefusals']))
                clients={'examples':client,'foreign':original.client_for_foreign(client,node,work/'foreign',phase_output/'foreign-controls')}
                probe=Probe(node,file_identity(native['latentd'],512*1024**2));targets={}
                source=signed/original.SERVICE
                for tenant in original.TENANTS:
                    c=clients[tenant]
                    published=c.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                        '--operation-id','rust-limit-publish-'+tenant,'--expected-generation','0')
                    require(published['data']['release']['digest']==identities['component.wasm']['sha256'], 'rust-limit-same-component')
                    publication=published['data']['operation']['publication']['id']
                    manifest=c.directory/'deployment.json';write_json(manifest,original.deployment(read_json(source/'deployment.json'),tenant))
                    target=deploy(c,manifest,publication)
                    grants=original.grant(c,node,publication,tenant,peers[tenant])
                    targets[tenant]=deploy(c,manifest,publication,generation=str(target['generation']),grants=grants)
                if phase=='baseline':
                    for tenant,library in (('examples','waki'),('foreign','golem')):
                        item=original.invoke(clients[tenant],node,targets[tenant],peers,tenant,library,'alpha',original.cases()[0],probe,phase_output,'baseline-'+library)
                        write_json(phase_output/('case-'+item['case']+'.json'),item)
                        record['attempts'].append({'phase':phase,'client':library,'kind':'parsed-json',
                            'evidence':file_identity(phase_output/('case-'+item['case']+'.json'))})
                    spec=next(s for s in original.cases() if s[0]=='partial-complete')
                    item=original.invoke(clients['foreign'],node,targets['foreign'],peers,'foreign','golem','delta',spec,probe,phase_output,'node-stop-pending')
                    # Retain bounded native bytes before any new baseline assertion.
                    raw=original.retain_terminal_timer(node,phase_output,'baseline')
                    terminal=baseline_timer(raw)
                    write_json(phase_output/'baseline-real-timer.json',{'case':item,'terminal':terminal})
                    record['attempts'].append({'phase':phase,'client':'golem','kind':'real-timer-pending-release'})
                else:
                    item=boundary_call(clients['examples'],node,targets['examples'],peers,'examples',phase,probe,phase_output,memory_context)
                    record['attempts'].append({'phase':phase,'kind':'isolated-ceiling','evidence':file_identity(phase_output/('case-'+phase+'.json'))})
                    library='waki' if phase=='timer-one' else 'golem'
                    fresh_result=original.invoke(clients['foreign'],node,targets['foreign'],peers,'foreign',library,'delta',original.cases()[0],probe,phase_output,'fresh-'+phase)
                    write_json(phase_output/('case-fresh-'+phase+'.json'),fresh_result)
                    if phase == 'memory-three-mib':
                        # Both calls use this same live node/cell; original.invoke
                        # also requires real parsed JSON, peers, and retirement.
                        differential = complete_memory_differential(item, fresh_result)
                        write_json(phase_output/'memory-differential.json', differential)
                    record['attempts'].append({'phase':phase,'client':library,'kind':'same-cell-opposite-fresh'})
                for index,tenant in enumerate(original.TENANTS):
                    original.retire(clients[tenant],probe,targets[tenant],phase_output,tenant+'-final',population=2-index)
                    delete_all(clients[tenant],[targets[tenant]['name']])
                stop(client,node);shutdown=stopped_record(node)
                require(shutdown['reaped'] is True and shutdown['record']['clean'] is True,'rust-limit-clean-reaped-shutdown')
                final_peers={t:p.close() for t,p in peers.items()}
                require(all(v['openConnections']==v['listeningOrigins']==0 and v['state']=='stopped'
                    and v['acceptedConnections']<=32 and v['failure'] is None
                    and v['rejectedRequests']==v['connectionBoundRejections']==v['committedMutations']==0
                    for v in final_peers.values()),'rust-limit-final-bounded-peer-retirement')
                public=json.dumps(final_peers,ensure_ascii=True).encode()
                require(all(secret not in public and secret.removeprefix(b'Bearer ') not in public
                    for secret in private_values),'rust-limit-no-retained-credential-bytes')
                write_json(phase_output/'final.json',{'shutdown':shutdown,'peers':final_peers,'startup':node.startup_record})
                record['phases'].append({'phase':phase,'startup':node.startup_record,'shutdown':shutdown,'peers':final_peers})
        require(len(record['attempts'])==9 and len(record['phases'])==4 and not record['cleanupRefusals']
            and identities=={n:file_identity(artifact/n) for n in identities},'rust-limit-exact-nine-and-original-unchanged')
        record['status']='passed';write_json(output/'qualification.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage)
        try:write_json(output/'FAILED.json',record)
        except BaseException:pass
        raise

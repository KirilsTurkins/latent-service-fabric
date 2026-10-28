"""Exact compiler-private bridge for the selected managed accepted-work port."""
from __future__ import annotations

import re

IDENTITY = 'latent:dotnet-managed-work/owner@0.1.0'
PACKAGE = 'latent:dotnet-managed-work@0.1.0'
PROFILE = 'dotnet-managed-accepted-work-v1'
PRIVATE = '''
package latent:dotnet-managed-work@0.1.0 {
  interface owner {
    reserve: func(kind: u32, parent-generation: u64, parent-id: u64) -> result<tuple<u64, u64>, u32>;
    settle: func(generation: u64, id: u64) -> result<_, u32>;
    close: func() -> result<_, u32>;
    context: func(generation: u64, id: u64);
  }
}
'''


def selected(declared: list[str]) -> bool:
    from tools.dotnet_guest import runtime
    return {runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM} <= set(declared)


def without_private(text: str) -> str:
    package = re.compile(r'(?m)^package latent:dotnet-managed-work@0\.1\.0 \{\s*'
        r'interface owner \{\s*reserve: func\(kind: u32, parent-generation: u64, parent-id: u64\) -> result<tuple<u64, u64>, u32>;\s*'
        r'settle: func\(generation: u64, id: u64\) -> result<_, u32>;\s*close: func\(\) -> result<_, u32>;\s*'
        r'context: func\(generation: u64, id: u64\);\s*\}\s*\}\s*')
    imports = re.compile(r'(?m)^[ \t]+import latent:dotnet-managed-work/owner@0\.1\.0;\n')
    if len(package.findall(text)) != 1 or len(imports.findall(text)) != 1:
        raise ValueError('dotnet-managed-work-private-source-shape')
    restored = package.sub('', imports.sub('', text))
    if 'latent:dotnet-managed-work' in restored:
        raise ValueError('dotnet-managed-work-private-source-remainder')
    return restored


def private_interface(graph: dict, direction: str) -> bool:
    from tools.dotnet_guest.internal_io import interface_name
    identifiers = {item['interface']['id'] for world in graph['worlds'] for item in world[direction].values()
        if 'interface' in item and interface_name(graph, item['interface']['id']) == IDENTITY}
    if not identifiers:
        return False
    if len(identifiers) != 1:
        raise ValueError('dotnet-managed-work-private-interface-count')
    interface = graph['interfaces'][next(iter(identifiers))]
    if interface['types']:
        raise ValueError('dotnet-managed-work-private-interface-types')

    def shape(value, depth=0):
        if value is None or value in ('u32', 'u64'):
            return value
        if type(value) is not int or not 0 <= value < len(graph['types']) or depth >= 3:
            raise ValueError('dotnet-managed-work-private-type')
        row = {key: item for key, item in graph['types'][value].items() if key != 'docs'}
        if set(row) != {'name', 'owner', 'kind'} or row['name'] is not None or row['owner'] is not None:
            raise ValueError('dotnet-managed-work-private-type-owner')
        kind = row['kind']
        if type(kind) is dict and set(kind) == {'tuple'} and set(kind['tuple']) == {'types'}:
            values = kind['tuple']['types']
            if type(values) is not list or len(values) != 2:
                raise ValueError('dotnet-managed-work-private-tuple')
            return ('tuple', *(shape(item, depth + 1) for item in values))
        if type(kind) is dict and set(kind) == {'result'} and set(kind['result']) == {'ok', 'err'}:
            return ('result', shape(kind['result']['ok'], depth + 1), shape(kind['result']['err'], depth + 1))
        raise ValueError('dotnet-managed-work-private-type-kind')

    expected = {
        'reserve': ([('kind', 'u32'), ('parent-generation', 'u64'), ('parent-id', 'u64')], ('result', ('tuple', 'u64', 'u64'), 'u32')),
        'settle': ([('generation', 'u64'), ('id', 'u64')], ('result', None, 'u32')),
        'close': ([], ('result', None, 'u32')),
        'context': ([('generation', 'u64'), ('id', 'u64')], None),
    }
    if set(interface['functions']) != set(expected):
        raise ValueError('dotnet-managed-work-private-operations')
    for name, (parameters, result) in expected.items():
        row = {key: value for key, value in interface['functions'][name].items() if key != 'docs'}
        keys = {'name', 'kind', 'params'} | ({'result'} if result is not None else set())
        if (set(row) != keys or row['name'] != name or row['kind'] != 'freestanding'
                or row['params'] != [{'name': key, 'type': value} for key, value in parameters]
                or shape(row.get('result')) != result):
            raise ValueError('dotnet-managed-work-private-operation-shape')
    return True


# Recomputed by the actual pinned CoreLib metadata control, before edits.
REWRITE_RECEIPT = {'patch': 'latent.dotnet.managed-accepted-work.v1',
 'modifiedOriginalMethods': {'System.Void System.Threading.QueueUserWorkItemCallback::Execute()': '24d788dd686009bd9c37633d78bbe221e0405ebac6e4639a25900ea43a40ffda',
                             'System.Void System.Threading.QueueUserWorkItemCallback`1::Execute()': '83b3d36f9275ca06a5035475ddf254407c5f2466bb85ba67489d0d4c2ec7c2ae',
                             'System.Void System.Threading.QueueUserWorkItemCallbackDefaultContext::Execute()': '7fa5fdbfc8cfb1b4eea8eef334152c9827e02ebcc7af19488af4533a31af3445',
                             'System.Void System.Threading.QueueUserWorkItemCallbackDefaultContext`1::Execute()': 'c1e6ffae01dbfc05922b307ef4ecef2d51106d81de81831cf10ca510028f53d5',
                             'System.Void System.Threading.Tasks.Task::ScheduleAndStart(System.Boolean)': 'e8dc768f03b492707419b8a0b42c737d09511477283706c247d7c2ea23b69f6f',
                             'System.Void System.Threading.Tasks.Task::ContinueWithCore(System.Threading.Tasks.Task,System.Threading.Tasks.TaskScheduler,System.Threading.CancellationToken,System.Threading.Tasks.TaskContinuationOptions)': '3b191683964cabe022ef170ac505707bbc8f86d9859c60e5804c4a3be512a588',
                             'System.Void System.Threading.Tasks.Task::FinishStageThree()': 'c9a030644a719cee1334e3f1c7d20cc3cfbc54e009d98c3a9653c506fc38118a',
                             'System.Void System.Threading.Tasks.UnwrapPromise`1::.ctor(System.Threading.Tasks.Task,System.Boolean)': '983681313253b07ab4db7856e41e50a713ce6a8a3a27e00a9097721ffb9f9fd4',
                             'System.Void System.Threading.Tasks.UnwrapPromise`1::ProcessInnerTask(System.Threading.Tasks.Task)': '4a3f34930eb1861aabe76311974eb6fa9acfcc2139e5f0b3fb0df6aa16f8f8c5',
                             'System.Void System.Threading.Tasks.TaskExceptionHolder::MarkAsHandled(System.Boolean)': 'fed64c98d93669065af30688e9644356f0073492179248c2c2b7db5312bb83b6',
                             'System.Void System.Threading.Tasks.Task::ExecuteWithThreadLocal(System.Threading.Tasks.Task&,System.Threading.Thread)': 'a32966dad0b1ca31ea2dea3b9043f8b45b6d47fad8efdcdfd856d34cca8c7f1b',
                             'System.Void System.Threading.Tasks.Task/<>c::<.cctor>b__289_0(System.Object)': '3933c87a0c328cf8deb495fa633edb6b149164c1c01e54878872fad89f86e648',
                             'System.Runtime.CompilerServices.IAsyncStateMachineBox System.Runtime.CompilerServices.AsyncTaskMethodBuilder`1::GetStateMachineBox(TStateMachine&,System.Threading.Tasks.Task`1<TResult>&)': '10f360a3fb90041302a4a06fc3b8b6347f7b0d27ba07cd6fba5af0d068b5a7a4',
                             'System.Void System.Threading.ThreadPoolWorkQueueThreadLocals::TransferLocalWork()': '20de413ab84da45069699cc7081077ec8b05a780c7f3a35a99c833cdfb0e6a38',
                             'System.Void System.Threading.ThreadPoolWorkQueue::Enqueue(System.Object,System.Boolean)': '4c5c012afe0e5aa5c2a4cdc51aba12426e0d871f41d0a1db82a8ff5a920fa085',
                             'System.Void System.Threading.ThreadPoolWorkQueue::EnqueueAtHighPriority(System.Object)': 'b6e96c60ed73aaae51ae1e20479b4c8a7a3b1a4b3c204472a0abefc10cd5d7df',
                             'System.Boolean System.Threading.ThreadPoolWorkQueue::LocalFindAndPop(System.Object)': '68f914a3793366fa56a9531a97333b666d0778025ad0bfa2dd133fe74e728eaa',
                             'System.Void System.Threading.ThreadPoolWorkQueue::DispatchWorkItem(System.Object,System.Threading.Thread)': '95d2738f3cf3a7ad5bafb7e9b400b22fe0ef162fe08f17b8b036fbf2890e855c'},
 'copiedRegistryMethods': 46,
 'taskIdentity': 'actual-task-unwrap-promise-and-inner',
 'requiredContinuationIdentity': 'actual-state-machine-box-before-await-registration',
 'queueAdmission': 'before-original-enqueue-with-fault-rollback',
 'completion': 'after-original-finish-continuations',
 'context': 'private-key-original-immutable-map-original-notifications',
 'contextSourceTypes': ['System.Threading.Tasks.Task',
                        'System.Threading.QueueUserWorkItemCallback',
                        'System.Threading.QueueUserWorkItemCallback`1',
                        'System.Threading.QueueUserWorkItemCallbackDefaultContext',
                        'System.Threading.QueueUserWorkItemCallbackDefaultContext`1'],
 'closing': 'original-native-close-and-live-parent-only',
 'join': 'original-task-wait-dispatch-with-readiness-each-iteration',
 'unobservedFaults': 'original-task-exception-retained-result-owner',
 'privateRootBridge': 'exact-Task-UnsafeAccessor-static-forwarders',
 'structuralRecordLimit': 32,
 'structuralQueueLimit': 64,
 'authoritativeLimits': 'original-activation-owner-ledger',
 'newAssemblyReferences': 0,
 'qualified': False}


# v1 remains an immutable historical receipt. The selected v2 additionally
# binds each original TimerQueueTimer producer and its native Timer owner.
TIMER_REWRITE_RECEIPT = {'patch': 'latent.dotnet.managed-accepted-work.v2',
 'modifiedOriginalMethods': {'System.Void System.Threading.QueueUserWorkItemCallback::Execute()': '24d788dd686009bd9c37633d78bbe221e0405ebac6e4639a25900ea43a40ffda',
                             'System.Void System.Threading.QueueUserWorkItemCallback`1::Execute()': '83b3d36f9275ca06a5035475ddf254407c5f2466bb85ba67489d0d4c2ec7c2ae',
                             'System.Void System.Threading.QueueUserWorkItemCallbackDefaultContext::Execute()': '7fa5fdbfc8cfb1b4eea8eef334152c9827e02ebcc7af19488af4533a31af3445',
                             'System.Void System.Threading.QueueUserWorkItemCallbackDefaultContext`1::Execute()': 'c1e6ffae01dbfc05922b307ef4ecef2d51106d81de81831cf10ca510028f53d5',
                             'System.Void System.Threading.Tasks.Task::ScheduleAndStart(System.Boolean)': 'e8dc768f03b492707419b8a0b42c737d09511477283706c247d7c2ea23b69f6f',
                             'System.Void System.Threading.Tasks.Task::ContinueWithCore(System.Threading.Tasks.Task,System.Threading.Tasks.TaskScheduler,System.Threading.CancellationToken,System.Threading.Tasks.TaskContinuationOptions)': '3b191683964cabe022ef170ac505707bbc8f86d9859c60e5804c4a3be512a588',
                             'System.Void System.Threading.Tasks.Task::FinishStageThree()': 'c9a030644a719cee1334e3f1c7d20cc3cfbc54e009d98c3a9653c506fc38118a',
                             'System.Void System.Threading.Tasks.UnwrapPromise`1::.ctor(System.Threading.Tasks.Task,System.Boolean)': '983681313253b07ab4db7856e41e50a713ce6a8a3a27e00a9097721ffb9f9fd4',
                             'System.Void System.Threading.Tasks.UnwrapPromise`1::ProcessInnerTask(System.Threading.Tasks.Task)': '4a3f34930eb1861aabe76311974eb6fa9acfcc2139e5f0b3fb0df6aa16f8f8c5',
                             'System.Void System.Threading.Tasks.TaskExceptionHolder::MarkAsHandled(System.Boolean)': 'fed64c98d93669065af30688e9644356f0073492179248c2c2b7db5312bb83b6',
                             'System.Void System.Threading.Tasks.Task::ExecuteWithThreadLocal(System.Threading.Tasks.Task&,System.Threading.Thread)': 'a32966dad0b1ca31ea2dea3b9043f8b45b6d47fad8efdcdfd856d34cca8c7f1b',
                             'System.Void System.Threading.Tasks.Task/<>c::<.cctor>b__289_0(System.Object)': '3933c87a0c328cf8deb495fa633edb6b149164c1c01e54878872fad89f86e648',
                             'System.Runtime.CompilerServices.IAsyncStateMachineBox System.Runtime.CompilerServices.AsyncTaskMethodBuilder`1::GetStateMachineBox(TStateMachine&,System.Threading.Tasks.Task`1<TResult>&)': '10f360a3fb90041302a4a06fc3b8b6347f7b0d27ba07cd6fba5af0d068b5a7a4',
                             'System.Void System.Threading.ThreadPoolWorkQueueThreadLocals::TransferLocalWork()': '20de413ab84da45069699cc7081077ec8b05a780c7f3a35a99c833cdfb0e6a38',
                             'System.Void System.Threading.ThreadPoolWorkQueue::Enqueue(System.Object,System.Boolean)': '4c5c012afe0e5aa5c2a4cdc51aba12426e0d871f41d0a1db82a8ff5a920fa085',
                             'System.Void System.Threading.ThreadPoolWorkQueue::EnqueueAtHighPriority(System.Object)': 'b6e96c60ed73aaae51ae1e20479b4c8a7a3b1a4b3c204472a0abefc10cd5d7df',
                             'System.Boolean System.Threading.ThreadPoolWorkQueue::LocalFindAndPop(System.Object)': '68f914a3793366fa56a9531a97333b666d0778025ad0bfa2dd133fe74e728eaa',
                             'System.Void System.Threading.ThreadPoolWorkQueue::DispatchWorkItem(System.Object,System.Threading.Thread)': '95d2738f3cf3a7ad5bafb7e9b400b22fe0ef162fe08f17b8b036fbf2890e855c',
                             'System.Boolean System.Threading.TimerQueue::UpdateTimer(System.Threading.TimerQueueTimer,System.UInt32,System.UInt32)': 'a6718748ddf98afce1b550bd346cf0140de8944544f600816362c15b61fd4b6b',
                             'System.Void System.Threading.TimerQueue::DeleteTimer(System.Threading.TimerQueueTimer)': '97df4a648d3a936be0a512e16dff243bee88b9b77a44c5865e8c6f3f0d4f2f8d',
                             'System.Void System.Threading.TimerQueue::FireNextTimers()': '5e78e327e830b1b1543c560634848e2244663e3ec32686f5d6f8bd7904a11f09',
                             'System.Void System.Threading.TimerQueueTimer::Fire(System.Boolean)': '7aac3cfdb1d33f5f32c3ef6760cc61596a805b5e33a26cee5d07ced09ec8962b',
                             'System.Void System.Threading.TimerQueueTimer::CallCallback(System.Boolean)': '078f485b1d05ad88167bae8b04cb7c683ccb6987620d2b433507ec9c52e3097d'},
 'copiedRegistryMethods': 58,
 'taskIdentity': 'actual-task-unwrap-promise-and-inner',
 'requiredContinuationIdentity': 'actual-state-machine-box-before-await-registration',
 'queueAdmission': 'before-original-enqueue-with-fault-rollback',
 'completion': 'after-original-finish-continuations',
 'context': 'private-key-original-immutable-map-original-notifications',
 'contextSourceTypes': ['System.Threading.Tasks.Task',
                        'System.Threading.QueueUserWorkItemCallback',
                        'System.Threading.QueueUserWorkItemCallback`1',
                        'System.Threading.QueueUserWorkItemCallbackDefaultContext',
                        'System.Threading.QueueUserWorkItemCallbackDefaultContext`1'],
 'closing': 'original-native-close-and-live-parent-only',
 'join': 'original-task-wait-dispatch-with-readiness-each-iteration',
 'unobservedFaults': 'original-task-exception-retained-result-owner',
 'privateRootBridge': 'exact-Task-UnsafeAccessor-static-forwarders',
 'structuralRecordLimit': 32,
 'structuralQueueLimit': 64,
 'structuralTimerLimit': 32,
 'timerAdmission': 'original-TimerQueueTimer-before-active-list-mutation',
 'timerRetirement': 'original-disarmed-no-accepted-queued-running-or-required-callback',
 'timerCallbackContext': 'original-ExecutionContext-values-with-private-live-timer-owner',
 'authoritativeLimits': 'original-activation-owner-ledger',
 'newAssemblyReferences': 0,
 'qualified': False}


def validate_rewrite(value: dict) -> None:
    if type(value) is not dict:
        raise ValueError('dotnet-managed-work-rewrite-receipt')
    expected_receipt = (TIMER_REWRITE_RECEIPT if value.get('patch') == TIMER_REWRITE_RECEIPT['patch']
        else REWRITE_RECEIPT)
    if (set(value) != set(expected_receipt)
            or any(type(value.get(key)) is not type(expected) or value[key] != expected
                for key, expected in expected_receipt.items())):
        raise ValueError('dotnet-managed-work-rewrite-receipt')


HTTP_REWRITE = {
    'profile':'dotnet-required-http-content-work-v1',
    'method':'System.Void System.Net.Http.WasiRequestWrapper/<SendRequestAsync>d__4::MoveNext()',
    'originalBodyDigest':'sha256:aecd9e09ae0451697c5cb6281cbe81c2ccca078fd7c78e9c5a3acc0d1736b4b8',
    'modifiedOriginalMethods':1, 'task':'actual-original-SendContent-return',
    'error':'unchanged-request-future', 'transport':'unchanged-original-WASI-handler',
    'completion':'actual-content-task-before-physical-drain', 'qualified':False,
}


def validate_http_rewrite(value: dict) -> None:
    if (type(value) is not dict or set(value) != set(HTTP_REWRITE)
            or any(type(value.get(key)) is not type(expected) or value[key] != expected
                for key, expected in HTTP_REWRITE.items())):
        raise ValueError('dotnet-required-content-work-rewrite-receipt')


ABORT_REWRITE = {
    'profile': 'dotnet-request-abort-cleanup-v1',
    'method': 'System.Void System.Net.Http.WasiRequestWrapper::Dispose()',
    'originalBodyDigest': 'sha256:63c5a116d410596de909966cc8c43e574d39491496edeeaa8db44ed31e65be8f',
    'successfulCloseBodyDigest': 'sha256:f7bdf561babff64617ae550ac89eeeba27dd08d9cd5d09f15e2475951f49cd5a',
    'protectedDisposeBodyDigest': 'sha256:242ab25d6c4af1de65c1b1c83742a554a892e2873282048e51cbfb6e1694ff33',
    'cleanup': 'original-protected-Dispose(true)-then-GC-suppression',
    'body': 'abort-not-successful-finish', 'originalFailure': 'original-handler-rethrow',
    'inputAndFutureCleanup': 'unchanged', 'modifiedOriginalMethods': 1,
    'generatedHelpers': 1, 'newHostImports': 0, 'qualified': False,
}


def validate_abort_rewrite(value: dict) -> None:
    if (type(value) is not dict or set(value) != set(ABORT_REWRITE)
            or any(type(value.get(key)) is not type(expected) or value[key] != expected
                for key, expected in ABORT_REWRITE.items())):
        raise ValueError('dotnet-request-abort-cleanup-rewrite-receipt')


# Qualification-only two-scalar port. No default compiler selection uses it.
STAGE_PROFILE = 'dotnet-managed-stage-diagnostic-v3'
STAGE_IDENTITY = 'latent:development-dotnet-stage/stage@0.3.0'
STAGE_DATA = 'sdk/dotnet-guest/tests/fixtures/root-return/managed-stage'
STAGE_BASE_CORELIB = 'sha256:bc449bac32313b547de63b4b852f1ff619ca91b22a24cc36f3526fa09df7e348'
STAGE_LIBRARY_SHA = '406c1c6e0ffe1fc0d271be11c608bb6a39615144311e20fcae41c590de2c4106'
STAGE_ROOT_SHA = '5d6a48c15227a1eae93501ea4bc901fe0e30cdb516fd74e5191cdb4c061a2b45'
STAGE_AUX_SHA = '86da34a0b3be9178771872aa906c1bc14277108f1f7e42f325d0911e74fa956a'
STAGE_CASE = 'dotnet_managed_stage_diagnostic_preserves_failed_root_return_boundary'


def stage_library(text: str) -> tuple[str, dict]:
    """Select the actual returned promise; never inspect its Exception or join it."""
    import hashlib
    if hashlib.sha256(text.encode()).hexdigest() != STAGE_LIBRARY_SHA:
        raise ValueError('managed-stage-library-preimage')
    edits = (
        ('    private static FaultIdentity? faultIdentity;\n',
         '    private static FaultIdentity? faultIdentity;\n    private static Task? managedStageTask;\n'
         '    public static Task? ManagedStageTask => managedStageTask;\n'),
        ('faultIdentity is not null)\n', 'faultIdentity is not null || managedStageTask is not null)\n'),
        ('                Pending(Task.Run(UnobservedFault));\n',
         '                managedStageTask = Task.Run(UnobservedFault);\n                Pending(managedStageTask);\n'),
        ('        Pending(child);\n        Pending(ObserveFault(child, original));\n',
         '        Pending(child);\n        managedStageTask = child;\n        Pending(ObserveFault(child, original));\n'),
    )
    selected = text
    for old, new in edits:
        if selected.count(old) != 1:
            raise ValueError('managed-stage-library-selection-shape')
        selected = selected.replace(old, new)
    inverse = selected
    for old, new in reversed(edits):
        if inverse.count(new) != 1:
            raise ValueError('managed-stage-library-inverse-shape')
        inverse = inverse.replace(new, old)
    if inverse != text:
        raise ValueError('managed-stage-library-inverse')
    return selected, {'profile': STAGE_PROFILE, 'originalSHA256': STAGE_LIBRARY_SHA,
        'selectedSHA256': hashlib.sha256(selected.encode()).hexdigest(), 'originalSourceInverseExact': True,
        'selection': 'actual-returned-Task.Run-promise', 'readsTaskException': False, 'applicationRootJoinAdded': False}


def stage_private_interface(graph: dict, direction: str) -> bool:
    from tools.dotnet_guest.internal_io import interface_name
    identifiers = {row['interface']['id'] for world in graph['worlds'] for row in world[direction].values()
        if 'interface' in row and interface_name(graph, row['interface']['id']) == STAGE_IDENTITY}
    if not identifiers:
        return False
    if len(identifiers) != 1:
        raise ValueError('managed-stage-private-interface-count')
    interface = graph['interfaces'][next(iter(identifiers))]
    functions = interface['functions']
    if interface['types'] or set(functions) != {'emit'}:
        raise ValueError('managed-stage-private-interface-shape')
    row = {k: v for k, v in functions['emit'].items() if k != 'docs'}
    if (set(row) not in ({'name', 'kind', 'params'}, {'name', 'kind', 'params', 'result'}) or row.get('result') is not None or row['name'] != 'emit' or row['kind'] != 'freestanding'
            or row['params'] != [{'name': 'stage', 'type': 'u32'}, {'name': 'guard', 'type': 'u32'}]):
        raise ValueError('managed-stage-private-function-shape')
    return True


def stage_without_private(text: str) -> str:
    package = re.compile(r'(?m)^package latent:development-dotnet-stage@0\.3\.0 \{\s*'
        r'interface stage \{\s*emit: func\(stage: u32, guard: u32\);\s*\}\s*\}\s*')
    imported = re.compile(r'(?m)^[ \t]+import latent:development-dotnet-stage/stage@0\.3\.0;\n')
    if len(package.findall(text)) != 1 or len(imported.findall(text)) != 1:
        raise ValueError('managed-stage-private-source-shape')
    result = package.sub('', imported.sub('', text))
    if 'latent:development-dotnet-stage' in result:
        raise ValueError('managed-stage-private-source-remainder')
    return result


def stage_export_helper(name: str, text: str) -> tuple[str, dict]:
    import hashlib
    if name != 'ServiceWorld.wit.Exports.examples.greeting.ApiExportsInterop.cs' or hashlib.sha256(text.encode()).hexdigest() != STAGE_AUX_SHA:
        raise ValueError('managed-stage-auxiliary-helper-preimage')
    edits = (
        ('            global::LsfManagedWorkRoot.Initialize();\n',
         '            global::LsfManagedWorkRoot.Initialize();\n            global::LsfManagedStageRoot.Install();\n'),
        ('            var ret = ApiExportsImpl.Probe((unchecked((uint)(p0))));\n',
         '            var ret = ApiExportsImpl.Probe((unchecked((uint)(p0))));\n'
         '            global::LsfManagedStageRoot.Select(global::OutsideRootDrain.Library.ManagedStageTask);\n'
         '            global::LsfManagedStageRoot.Emit(22u, 0u);\n'),
        ('                ProbeTaskReturn(unchecked((int)0x4A430001u));\n',
         '                global::LsfManagedStageRoot.Emit(19u, 0u);\n'
         '                ProbeTaskReturn(unchecked((int)0x4A430001u));\n'),
        ('                ProbeTaskReturn(unchecked((int)0x4A430002u));\n',
         '                global::LsfManagedStageRoot.Emit(20u, 0u);\n'
         '                ProbeTaskReturn(unchecked((int)0x4A430002u));\n'),
        ('                ProbeTaskReturn(unchecked((int)0x4A430003u));\n',
         '                global::LsfManagedStageRoot.Emit(21u, 0u);\n'
         '                ProbeTaskReturn(unchecked((int)0x4A430003u));\n'),
    )
    selected = text
    for old, new in edits:
        if selected.count(old) != 1:
            raise ValueError('managed-stage-export-insertion-shape')
        selected = selected.replace(old, new)
    inverse = selected
    for old, new in reversed(edits):
        inverse = inverse.replace(new, old)
    if inverse != text:
        raise ValueError('managed-stage-auxiliary-helper-inverse')
    return selected, {'profile': STAGE_PROFILE, 'originalAuxiliarySHA256': STAGE_AUX_SHA,
        'selectedSHA256': hashlib.sha256(selected.encode()).hexdigest(), 'originalAuxiliaryInverseExact': True,
        'joinCatchDrainFinishTaskReturnChanged': False, 'originalFaultQualified': False}


def stage_root_bridge(text: str, generated: dict[str, str]) -> tuple[str, dict]:
    import hashlib
    if hashlib.sha256(text.encode()).hexdigest() != STAGE_ROOT_SHA:
        raise ValueError('managed-stage-root-bridge-preimage')
    interfaces = [source for source in generated.values()
        if 'public interface IStageImports' in source and 'static' in source and 'Emit(' in source]
    if len(interfaces) != 1:
        raise ValueError('managed-stage-generated-import-count')
    names = re.findall(r'(?m)^namespace ([A-Za-z_][A-Za-z_0-9.]*)\s*[;{]', interfaces[0])
    interops = [source for source in generated.values() if 'DllImportAttribute("'+STAGE_IDENTITY+'", EntryPoint = "emit")' in source]
    if (len(names) != 1 or interfaces[0].count('public static unsafe void Emit(uint stage, uint guard)') != 1
            or len(interops) != 1 or interops[0].count('public static extern void wasmImportEmit(int p0, int p1);') != 1):
        raise ValueError('managed-stage-generated-two-u32-import')
    addition = """
internal static class LsfManagedStageRoot
{
    [global::System.Runtime.CompilerServices.UnsafeAccessor(global::System.Runtime.CompilerServices.UnsafeAccessorKind.StaticMethod, Name = "LsfManagedStageInstall")]
    private static extern void InstallCore(global::System.Threading.Tasks.Task? type, global::System.Action<uint, uint> callback);
    [global::System.Runtime.CompilerServices.UnsafeAccessor(global::System.Runtime.CompilerServices.UnsafeAccessorKind.StaticMethod, Name = "LsfManagedStageSelect")]
    private static extern void SelectCore(global::System.Threading.Tasks.Task? type, global::System.Threading.Tasks.Task selected);
    internal static void Install() => InstallCore(null, global::@IMPORT@.IStageImports.Emit);
    internal static void Emit(uint stage, uint guard) => global::@IMPORT@.IStageImports.Emit(stage, guard);
    internal static void Select(global::System.Threading.Tasks.Task? selected)
    {
        if (selected is not null) SelectCore(null, selected);
    }
}
""".replace('@IMPORT@', names[0])
    selected = text + addition
    if selected.removesuffix(addition) != text:
        raise ValueError('managed-stage-root-bridge-inverse')
    return selected, {'profile': STAGE_PROFILE, 'originalRootSHA256': STAGE_ROOT_SHA,
        'selectedSHA256': hashlib.sha256(selected.encode()).hexdigest(), 'originalRootInverseExact': True,
        'newAssemblyReferences': 0, 'selectedImportNamespace': names[0]}


def stage_binding_source(compiler, source, world, output):
    """Add and retain the full private contract; inverse is source proof, not admission."""
    import json
    from tools.dotnet_guest_bindings import contract_graph
    from tools.rust_capsule_project import read_file, write_json, digest
    original = compiler.run('managed-stage-before-wit', compiler.wasm, 'component', 'wit', source, '--no-docs').decode()
    if len(original.encode()) > 4*1024**2 or STAGE_IDENTITY in original:
        raise ValueError('managed-stage-original-wit')
    opening = list(re.finditer(r'(?m)^world (%?[A-Za-z][A-Za-z0-9-]*) \{', original))
    if len(opening) != 1:
        raise ValueError('managed-stage-world-count')
    output.mkdir()
    selected = output/'selected.wit'
    package = read_file(compiler.vendor/STAGE_DATA/'private.wit', 4096).decode()
    if package != 'package latent:development-dotnet-stage@0.3.0 {\n  interface stage {\n    emit: func(stage: u32, guard: u32);\n  }\n}\n':
        raise ValueError('managed-stage-private-wit-bytes')
    offset = opening[0].end()
    selected.write_text(original[:offset]+'\n  import '+STAGE_IDENTITY+';'+original[offset:]+'\n'+package, encoding='utf-8', newline='\n')
    canonical = compiler.run('managed-stage-private-wit', compiler.wasm, 'component', 'wit', selected, '--no-docs').decode()
    if len(canonical.encode()) > 4*1024**2:
        raise ValueError('managed-stage-selected-wit-bound')
    (output/'original.wit').write_text(original, encoding='utf-8', newline='\n')
    restored = output/'inverse.wit'
    restored.write_text(stage_without_private(canonical), encoding='utf-8', newline='\n')
    before = contract_graph(json.loads(compiler.run('managed-stage-before-graph', compiler.wasm, 'component', 'wit', source, '--json')))
    inverse = contract_graph(json.loads(compiler.run('managed-stage-inverse-graph', compiler.wasm, 'component', 'wit', restored, '--json')))
    actual = contract_graph(json.loads(compiler.run('managed-stage-selected-graph', compiler.wasm, 'component', 'wit', selected, '--json')))
    if before != inverse or not stage_private_interface(actual, 'imports'):
        raise ValueError('managed-stage-entire-source-inverse')
    record = {'profile': STAGE_PROFILE, 'privateImport': STAGE_IDENTITY, 'originalDigest': digest(original.encode()),
        'selectedDigest': digest(read_file(selected)), 'sourceInverseExact': True,
        'privateImportRetainedInFinalIdentity': True, 'ordinaryHostAbiCompatible': False}
    write_json(compiler.commands.output/'managed-stage-wit.json', record)
    if len(canonical.encode()) > 512*1024:
        raise ValueError('managed-stage-signed-private-contract-bound')
    write_json(compiler.commands.output/'managed-stage-contract.json', {'profile': STAGE_PROFILE,
        'privateImport': STAGE_IDENTITY, 'selectedFullWit': canonical, 'selectedDigest': digest(canonical.encode())})
    return selected, record


class StagePort:
    """Exact diagnostic successor of the ordinary closed-filesystem derivation."""
    def __init__(self, base, assembly, targets, references, receipt, identity):
        self.base, self.assembly, self.targets, self.references = base, assembly, targets, references
        self.receipt, self.identity = receipt, identity

    def final_for(self, base):
        if base is not self.base:
            raise ValueError('managed-stage-foreign-corelib-chain')
        self.recheck()
        return self.assembly

    def recheck(self):
        from tools.build_observation import file_identity
        self.base.recheck()
        if (self.base.identity['digest'] != STAGE_BASE_CORELIB
                or file_identity(self.assembly, 'managed-stage-derived-corelib', 8*1024**2) != self.identity):
            raise ValueError('managed-stage-corelib-mutated')

    def finish(self, project, output):
        import json, shlex
        from tools.rust_capsule_project import read_file, write_json, digest
        self.recheck()
        refs = read_file(self.references, 64*1024).decode('utf-8-sig').splitlines()
        if refs != [str(self.assembly)]:
            raise ValueError('managed-stage-reference-binding')
        responses = list((project/'obj').rglob('*.rsp'))
        if len(responses) > 64:
            raise ValueError('managed-stage-response-count')
        matched, total = [], 0
        for path in responses:
            body = read_file(path, 1024**2); total += len(body)
            if total > 4*1024**2:
                raise ValueError('managed-stage-response-bytes')
            selected = [arg[3:] for arg in shlex.split(body.decode('utf-8-sig'))
                if arg.startswith('-r:') and __import__('pathlib').Path(arg[3:]).name == 'System.Private.CoreLib.dll']
            if selected:
                if selected != [str(self.assembly)]:
                    raise ValueError('managed-stage-actual-ilc-reference')
                matched.append({'digest': digest(body), 'size': len(body)})
        if len(matched) != 1:
            raise ValueError('managed-stage-actual-ilc-not-observed')
        result = {**self.receipt, 'nativeAotReferenceBinding': {'baseDigest': self.base.identity['digest'],
            'selectedDigest': self.identity['digest'], 'responseFiles': matched}}
        write_json(output/'managed-stage-overlay.json', result)
        return result


def stage_prepare(compiler, project, output):
    import json
    from pathlib import Path
    from xml.etree import ElementTree as XML
    from tools.dotnet_guest import http_errors
    from tools.build_observation import file_identity
    from tools.rust_capsule_project import read_file, write_json, digest
    base = compiler.filesystem_port
    if base is None or base.identity['digest'] != STAGE_BASE_CORELIB:
        raise ValueError('managed-stage-exact-final-corelib-required')
    base.recheck()
    owned = output/'managed-stage-port'; owned.mkdir()
    tool = owned/'tool'; tool.mkdir()
    source = read_file(compiler.vendor/STAGE_DATA/'ManagedStageOverlay.cs', 64*1024)
    (tool/'ManagedStageOverlay.cs').write_bytes(source)
    cecil = http_errors.cecil_path(compiler.tools)
    http_errors.require_digest(cecil, http_errors.CECIL_DIGEST, 'managed-stage-cecil')
    document = XML.Element('Project', Sdk='Microsoft.NET.Sdk')
    props = XML.SubElement(document, 'PropertyGroup')
    for key,value in {'TargetFramework':'net10.0','OutputType':'Exe','EnableDefaultCompileItems':'false',
        'ImplicitUsings':'enable','Nullable':'enable','UseSharedCompilation':'false','NuGetAudit':'false'}.items():
        XML.SubElement(props,key).text=value
    items=XML.SubElement(document,'ItemGroup'); XML.SubElement(items,'Compile',Include='ManagedStageOverlay.cs')
    XML.SubElement(items,'Reference',Include='Mono.Cecil',HintPath=http_errors.msbuild_literal(cecil))
    (tool/'Overlay.csproj').write_bytes(XML.tostring(document,encoding='utf-8',xml_declaration=True))
    (tool/'nuget.config').write_text('<configuration><packageSources><clear /></packageSources></configuration>\n',encoding='utf-8')
    (tool/'global.json').write_bytes(read_file(compiler.sdk/'global.json'))
    compiler.run('managed-stage-overlay-tool', compiler.dotnet, 'build', tool/'Overlay.csproj', '-c','Release',
        '-o',tool/'bin','--configfile',tool/'nuget.config','-p:UseSharedCompilation=false','-p:NuGetAudit=false')
    assembly, receipt = owned/'System.Private.CoreLib.dll', owned/'overlay.json'
    compiler.run('managed-stage-corelib-overlay', compiler.dotnet, tool/'bin/Overlay.dll', base.assembly, assembly, receipt)
    record = json.loads(read_file(receipt,64*1024))
    identity=file_identity(assembly,'managed-stage-derived-corelib',8*1024**2)
    if (record.get('profile') != STAGE_PROFILE or record.get('originalDigest') != STAGE_BASE_CORELIB
            or record.get('outputDigest') != identity['digest'] or record.get('cecilDigest') != http_errors.CECIL_DIGEST
            or record.get('originalInstructionsAndHandlersInverseExact') is not True
            or record.get('newAssemblyReferences') != 0 or record.get('newFields') != 3 or record.get('newMethods') != 7
            or len(record.get('modifiedMethods',{})) != 10 or record.get('maxEvents') != 16
            or record.get('actualWrittenBodiesVerified') is not True
            or record.get('branchNormalization') != {'method':'Finish','originalOffset':8,'originalTargetOffset':81,
                'originalOpcode':'brfalse.s','selectedOpcode':'brfalse','selectedMethodBytes':155,
                'shortBranchesChecked':103,'originalOpcodeRestoredByInverse':True}):
        raise ValueError('managed-stage-overlay-receipt')
    targets=owned/'ManagedStage.targets'; references=owned/'actual-reference.txt'
    target=XML.Element('Project'); entry=XML.SubElement(target,'Target',Name='LsfBindManagedStage',
        DependsOnTargets='LsfBindClosedFilesystem',BeforeTargets='WriteIlcRspFileForCompilation',
        AfterTargets='LsfBindClosedFilesystem',Condition="'$(RuntimeIdentifier)' == 'wasi-wasm'")
    group=XML.SubElement(entry,'ItemGroup')
    XML.SubElement(group,'_LsfStageCandidates',Include='@(IlcReference)',Condition="'%(IlcReference.Filename)' == 'System.Private.CoreLib' And '%(IlcReference.Extension)' == '.dll'")
    XML.SubElement(group,'_LsfStageUnknown',Include='@(_LsfStageCandidates)',Exclude=http_errors.msbuild_literal(base.assembly))
    XML.SubElement(entry,'Error',Condition="'@(_LsfStageCandidates->Count())' != '1'",Text='managed-stage-framework-reference-count')
    XML.SubElement(entry,'Error',Condition="'@(_LsfStageUnknown)' != ''",Text='managed-stage-unknown-framework-reference')
    XML.SubElement(entry,'Error',Condition="!Exists('"+http_errors.msbuild_literal(assembly)+"')",Text='managed-stage-derived-missing')
    group=XML.SubElement(entry,'ItemGroup');XML.SubElement(group,'IlcReference',Remove='@(_LsfStageCandidates)')
    XML.SubElement(group,'IlcReference',Include=http_errors.msbuild_literal(assembly))
    XML.SubElement(entry,'WriteLinesToFile',File=http_errors.msbuild_literal(references),Lines=http_errors.msbuild_literal(assembly),Overwrite='false',Encoding='UTF-8')
    targets.write_bytes(XML.tostring(target,encoding='utf-8',xml_declaration=True))
    document=XML.fromstring(read_file(project/'Capsule.csproj',64*1024));XML.SubElement(document,'Import',Project=http_errors.msbuild_literal(targets))
    (project/'Capsule.csproj').write_bytes(XML.tostring(document,encoding='utf-8',xml_declaration=True))
    evidence=compiler.commands.output/'managed-stage-overlay-inputs';evidence.mkdir()
    for name,path in (('ManagedStageOverlay.cs',tool/'ManagedStageOverlay.cs'),('Overlay.csproj',tool/'Overlay.csproj'),
        ('Overlay.dll',tool/'bin/Overlay.dll'),('Mono.Cecil.dll',cecil),('ManagedStage.targets',targets),('overlay.json',receipt)):
        (evidence/name).write_bytes(read_file(path,8*1024**2))
    write_json(evidence/'canonical-corelib-inputs.json', {'base': {'retainedPath': 'probe-inputs/final-System.Private.CoreLib.dll',
        'identity': base.identity}, 'selected': {'retainedPath': 'probe-inputs/managed-stage-System.Private.CoreLib.dll',
        'identity': identity}, 'sameCompletePayloadsRetainedOnce': True})
    if compiler.isolation is not None:
        compiler.isolation.protect_inputs(assembly,targets)
    port=StagePort(base,assembly,targets,references,record,identity)
    port.recheck()
    return port


def stage_package_selection(commands, contracts_tool, project, output, files, original_surface):
    """Separate packaging WIT overlay; application/compiler source identity is never retagged."""
    import json
    from tools.rust_capsule_project import read_file, read_json, write_json, digest, inventory
    original = files['wit/world.wit']
    marker=b'world service {'
    if original.count(marker)!=1 or STAGE_IDENTITY.encode() in original:
        raise ValueError('managed-stage-package-original-world')
    insertion=b'\n    import '+STAGE_IDENTITY.encode()+b';'
    selected=original.replace(marker,marker+insertion,1)
    if selected.replace(insertion,b'',1)!=original:
        raise ValueError('managed-stage-package-world-inverse')
    private_group=read_file(__import__('pathlib').Path(__file__).resolve().parents[2]/STAGE_DATA/'private.wit',4096)
    package=b'package latent:development-dotnet-stage@0.3.0'
    opening=package+b' {\n'
    if not private_group.startswith(opening) or not private_group.endswith(b'}\n'):
        raise ValueError('managed-stage-package-private-preimage')
    private=package+b';\n'+private_group[len(opening):-2]
    if private.replace(package+b';\n',opening,1)+b'}\n'!=private_group:
        raise ValueError('managed-stage-package-private-inverse')
    package_files={**files,'wit/world.wit':selected,
        'wit/deps/development-dotnet-stage/package.wit':private}
    sources=[{'path':name,'content':raw.decode()} for name,raw in package_files.items()
        if name.startswith('wit/') and name.endswith('.wit')]
    selected_input=output/'managed-stage-package-inputs.json'
    write_json(selected_input,{'world':project['world'],'sources':sources})
    derived=output/'managed-stage-selected-contracts'
    commands.run('managed-stage-selected-package-contracts',contracts_tool,selected_input,derived,'--development-managed-stage')
    surface=read_json(derived/'surface.json')
    if (surface['exports']!=original_surface['exports']
            or set(surface['imports'])!={*original_surface['imports'],STAGE_IDENTITY}):
        raise ValueError('managed-stage-selected-package-surface')
    for name in ('contracts.json','wit-lock.json','surface.json'):
        (output/('original-application-'+name)).write_bytes(read_file(output/name,4*1024**2))
        (output/name).write_bytes(read_file(derived/name,4*1024**2))
    write_json(output/'managed-stage-package-projection.json',{'profile':STAGE_PROFILE,
        'originalWorld':project['world'],'selectedWorld':project['world'],'originalWorldSourceDigest':digest(original),
        'selectedWorldSourceDigest':digest(selected),'privateSourceDigest':digest(private_group),'selectedPrivateSourceDigest':digest(private),
        'privateSourceInverseExact':True,
        'originalApplicationSourceInverseExact':True,'originalPublicExportsUnchanged':True,
        'originalApplicationInputInventory':digest(inventory(files)),
        'selectedPackagingInputInventory':digest(inventory(package_files)),
        'sourceIdentityRetagged':False,'ordinaryHostAbiCompatible':False})
    return package_files,surface


def stage_raw_generation(generated, output, *, check):
    """Complete raw C# BEFORE any auxiliary/stage projection guard; private only."""
    from pathlib import Path
    import hashlib, json
    names=sorted(p.name for p in generated.glob('*.cs'))
    if (len(names)>64 or len(set(n.casefold() for n in names))!=len(names)
            or any(len(n)>256 or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*\.cs',n) is None for n in names)):
        raise ValueError('managed-stage-raw-name-bound')
    bodies={};total=0
    for name in names:
        path=generated/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1024**2:
            raise ValueError('managed-stage-raw-file-bound')
        with path.open('rb') as stream:body=stream.read(1024**2+1)
        total+=len(body)
        if len(body)>1024**2 or total>4*1024**2:
            raise ValueError('managed-stage-raw-total-bound')
        bodies[name]=body
    manifest={'profile':STAGE_PROFILE,'phase':'before-auxiliary-stage-projection','actualNames':names,
        'totalBytes':total,'files':{n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in bodies.items()},
        'expectedFinalNames':19,'expectedFinalNamesAreNotRawCount':True}
    directory=output.with_name(output.name+'-managed-stage-raw')
    data=(json.dumps(manifest,separators=(',',':'))+'\n').encode()
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir() or {p.name for p in directory.iterdir()}!={*names,'raw-inventory.json'}:
            raise ValueError('managed-stage-raw-existing-shape')
        if (directory/'raw-inventory.json').read_bytes()!=data or any((directory/n).is_symlink()
                or (directory/n).read_bytes()!=b for n,b in bodies.items()):
            raise ValueError('managed-stage-raw-drift')
    else:
        if check:raise ValueError('managed-stage-raw-check-missing')
        directory.mkdir()
        with (directory/'raw-inventory.json').open('xb') as stream:stream.write(data)
        for name,body in bodies.items():
            with (directory/name).open('xb') as stream:stream.write(body)
    return manifest

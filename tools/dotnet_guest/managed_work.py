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


def validate_rewrite(value: dict) -> None:
    if (type(value) is not dict or set(value) != set(REWRITE_RECEIPT)
            or any(type(value.get(key)) is not type(expected) or value[key] != expected
                for key, expected in REWRITE_RECEIPT.items())):
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

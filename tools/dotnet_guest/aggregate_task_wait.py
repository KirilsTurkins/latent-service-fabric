"""Closed derivation identities: reference 40180463429 plus the pinned Pump delta.

The added Pump identity is a source-normalized five-instruction delta with exact
known-pin and inverse checks; its new signed qualification remains pending.
These are WASI CoreLib identities, not the reference host's
private token/opcode projections or a signed NativeAOT qualification claim.
"""
from __future__ import annotations

EXPECTED = {'cancellation': 'entry-token-before-IsSet;later-IsSet-before-token',
 'context': 'original-RunInternal-default-and-finally-restore',
 'countdown': 'original-SetOnCountdownMres-completion-actions-detach-finally',
 'deadline': 'one-original-monotonic-interval-original-Task.Delay-wake',
 'infiniteClock': 'no-added-clock-read-or-timeout-wake',
 'limitsChanged': False,
 'nesting': 'single-and-aggregate-save-restore-depth32',
 'nonWasi': 'original-MRES-Wait-entry-without-duplicate-validation',
 'originalMethods': [{'ilBytes': 46,
                      'ilSha256': 'sha256:87d5707683590051481de68a5c41d27654e0223f72d9d826950aa6bded0015fa',
                      'method': 'System.Void '
                                'System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[])',
                      'token': 100679295},
                     {'ilBytes': 31,
                      'ilSha256': 'sha256:3230751c809caea2191f78d05b867d24c6d54fc334e66ab2aae202af25d09355',
                      'method': 'System.Void '
                                'System.Threading.Tasks.Task::WaitAll(System.ReadOnlySpan`1<System.Threading.Tasks.Task>)',
                      'token': 100679296},
                     {'ilBytes': 85,
                      'ilSha256': 'sha256:01319d2a08ba4ae07b1e5c364d0b4fd338471aa848c34777c235a4e90c5b571e',
                      'method': 'System.Boolean '
                                'System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.TimeSpan)',
                      'token': 100679297},
                     {'ilBytes': 45,
                      'ilSha256': 'sha256:5968cd2411bfc34c2ecd8ef2211d03618cfbfe40c12ff05d72b6e8f8f45524b0',
                      'method': 'System.Boolean '
                                'System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32)',
                      'token': 100679298},
                     {'ilBytes': 38,
                      'ilSha256': 'sha256:dce230be52341bd676be3317c7898112d7795f4570f647eef7a2e4b4a50a4935',
                      'method': 'System.Void '
                                'System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Threading.CancellationToken)',
                      'token': 100679299},
                     {'ilBytes': 37,
                      'ilSha256': 'sha256:6343973682f40d3769ee6c682104d4cb968b473be63720a76cf5bd24511220c0',
                      'method': 'System.Boolean '
                                'System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32,System.Threading.CancellationToken)',
                      'token': 100679300},
                     {'ilBytes': 84,
                      'ilSha256': 'sha256:4964812ad96bbf22498f0b6aa72665266aab885ac8281a13244699fdcd49201a',
                      'method': 'System.Void '
                                'System.Threading.Tasks.Task::WaitAll(System.Collections.Generic.IEnumerable`1<System.Threading.Tasks.Task>,System.Threading.CancellationToken)',
                      'token': 100679301},
                     {'ilBytes': 471,
                      'ilSha256': 'sha256:244c14ca727b59a6291824b90984aa76c49bf5e091cf8bc00a8e10a187f4bb6d',
                      'method': 'System.Boolean '
                                'System.Threading.Tasks.Task::WaitAllCore(System.ReadOnlySpan`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)',
                      'token': 100679302},
                     {'ilBytes': 149,
                      'ilSha256': 'sha256:2b0fb5a58f02b0341e2b94dbcb1460307e1e7b256f994f4b0956bfcfa1bb6d00',
                      'method': 'System.Boolean '
                                'System.Threading.Tasks.Task::WaitAllBlockingCore(System.Collections.Generic.List`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)',
                      'token': 100679304}],
 'originalRemainders': {'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32)': '5a5592caa53d515863389f0c020a327c3f272e458b770d35338b188fe69b84d8',
                        'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32,System.Threading.CancellationToken)': 'b6136bfe54b26d68a2d338db706d3b11d79e4027f9d2bf77cd6854d2417ce448',
                        'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.TimeSpan)': 'c368afa04d1fe4b559749153a617dd6553d468c1e4a863aef58415f5003c6799',
                        'System.Boolean System.Threading.Tasks.Task::WaitAllBlockingCore(System.Collections.Generic.List`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)': '740c927c3ee850feaead6d3499aee054f75841deba816fc874f6e1a3050fd42a',
                        'System.Boolean System.Threading.Tasks.Task::WaitAllCore(System.ReadOnlySpan`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)': '024df85aad141a7fbeb96033e804074a3cff4c780cd3f1593fc6abe9efd7e74a',
                        'System.Void System.Threading.Tasks.Task::WaitAll(System.Collections.Generic.IEnumerable`1<System.Threading.Tasks.Task>,System.Threading.CancellationToken)': '292f872d0b8ea521e502c14ecc748e012d82fd3a5ef2b88620f398207525ed84',
                        'System.Void System.Threading.Tasks.Task::WaitAll(System.ReadOnlySpan`1<System.Threading.Tasks.Task>)': 'ae7e874f310b9cd0d0eefc9295f55ce76d4b68afb20efed4c39745963669fe28',
                        'System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[])': 'bf44312a953cac0dbb9a141c868b3b9bafa2b2987b7b2eafaf9e541e64533fa1',
                        'System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Threading.CancellationToken)': '70390981c18197ae07f882605344258c5c099af34ef34f030283f20f54843c1c'},
 'patch': 'latent.dotnet.wait-all.v2',
 'productionSelected': False,
 'profile': 'dotnet-aggregate-task-wait-candidate-v2',
 'qualificationComplete': False,
 'rewrittenBodies': {'System.Boolean System.Threading.ManualResetEventSlim::LsfAggregateWait(System.Int32,System.Threading.CancellationToken)': '7b0016525b2e1e4d09861ec83a466a501af971f3f66fb693913f8642f3b9846d',
                     'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32)': '5a5592caa53d515863389f0c020a327c3f272e458b770d35338b188fe69b84d8',
                     'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32,System.Threading.CancellationToken)': 'b6136bfe54b26d68a2d338db706d3b11d79e4027f9d2bf77cd6854d2417ce448',
                     'System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.TimeSpan)': 'c368afa04d1fe4b559749153a617dd6553d468c1e4a863aef58415f5003c6799',
                     'System.Boolean System.Threading.Tasks.Task::WaitAllBlockingCore(System.Collections.Generic.List`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)': '662fadeb080fe41da363edd9655d3f20a01de68225e7742d1b38f931f3d7b1f9',
                     'System.Boolean System.Threading.Tasks.Task::WaitAllCore(System.ReadOnlySpan`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)': '024df85aad141a7fbeb96033e804074a3cff4c780cd3f1593fc6abe9efd7e74a',
                     'System.Boolean System.Threading.WasiEventLoop::LsfAggregateReady()': 'b54b84931d18366cfa690fb0eebb61d741d7e934f19e18e845ccd91379bf15f7',
                     'System.Boolean System.Threading.WasiEventLoop::LsfAggregateWait(System.Threading.ManualResetEventSlim,System.Int32,System.Threading.CancellationToken)': '03e0dbdce59a4e54030b9d52668b62af5fbadc57620131ba3a1d7c62069994ad',
                     'System.Boolean System.Threading.WasiEventLoop::LsfWaitForActualTaskCompletion(System.Threading.Tasks.Task)': 'e0b5f760a33a70b36058344c1669d8e471b6d53e15c191c90734d5ee7ed3e09d',
                     'System.Int64 System.Threading.TimerQueue::PumpTimerQueue(System.Int64)': 'c0764f8a2d3cbcd5eafb2b1ea85b8ed1d188ea701abdc409974e5b02620eeb55',
                     'System.Void System.Threading.Tasks.Task::WaitAll(System.Collections.Generic.IEnumerable`1<System.Threading.Tasks.Task>,System.Threading.CancellationToken)': '292f872d0b8ea521e502c14ecc748e012d82fd3a5ef2b88620f398207525ed84',
                     'System.Void System.Threading.Tasks.Task::WaitAll(System.ReadOnlySpan`1<System.Threading.Tasks.Task>)': 'ae7e874f310b9cd0d0eefc9295f55ce76d4b68afb20efed4c39745963669fe28',
                     'System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[])': 'bf44312a953cac0dbb9a141c868b3b9bafa2b2987b7b2eafaf9e541e64533fa1',
                     'System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Threading.CancellationToken)': '70390981c18197ae07f882605344258c5c099af34ef34f030283f20f54843c1c',
                     'System.Void System.Threading.WasiEventLoop::CheckPollables(System.Object)': '818cd94aefe77153f3ee20caf301ae2a7580c3d8659b8f322257f4e137b24449',
                     'System.Void System.Threading.WasiEventLoop::LsfAggregateDispatch(System.Object)': 'df50cd158b730f304f7f3235b486c51eb479ab67419dda612e2080bd748f5b87'},
 'target': 'private-aggregate-original-IsSet',
 'timerPump': {'batch': 'detach-positive-batch-to-original-List(Instances.Length)-before-original-enumerator',
               'callbacks': 'original-foreach-Clear-finally-FailFast-preserved',
               'generatedFields': 0,
               'generatedHelpers': 0,
               'inverseExact': True,
               'method': 'System.Int64 System.Threading.TimerQueue::PumpTimerQueue(System.Int64)',
               'nativeOwners': 0,
               'originalBodyIdentity': 'e2e16791ceb1451206ea80c8e6b6842b9857b467e3b5f97a3238c67e9f1fc095',
               'originalIlBytes': 214,
               'originalIlSha256': 'sha256:e486da68fcceeed848c7b35adbf5956f7345b9e3e63a05553148b83d2d7ba44b',
               'originalToken': 100678800,
               'rewrittenBodyIdentity': 'c0764f8a2d3cbcd5eafb2b1ea85b8ed1d188ea701abdc409974e5b02620eeb55'},
 'waitEdge': 'original-MRES-Wait-only',
 'zeroPoll': 'original-bounded-pollable-detach-dispose'}

TIMER_BODIES = {'System.Void System.Threading.TimerQueue::DeleteTimer(System.Threading.TimerQueueTimer)': '97df4a648d3a936be0a512e16dff243bee88b9b77a44c5865e8c6f3f0d4f2f8d',
 'System.Void System.Threading.TimerQueue::SetNextTimer(System.Int64,System.Int64)': 'fbd678f159bf3f73bd97acdf9b59cb5073f46e551503f045a6959a4de99a7d1c',
 'System.Void System.Threading.TimerQueue::TimerHandler(System.Object)': 'f0d96beadf3c85c3a7912ec1d894528c2b1b7fe8a77aca41d2263e574330b9d9'}

ZERO_CACHE_BODIES = {'System.Void System.Threading.WasiEventLoop::CheckPollables(System.Object)': '721d297cf7e66afbb320299c85f6fe8a0b8c174c5f05250081c16230e8396dfe'}

def exact(value, expected):
    """Equality includes every nested type, so bool cannot impersonate an int."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(exact(value[key], item) for key, item in expected.items())
    if type(expected) is list:
        return len(value) == len(expected) and all(exact(left, right) for left, right in zip(value, expected))
    return value == expected


def validate(value):
    if not exact(value, EXPECTED):
        raise ValueError('task-wait-aggregate-rewrite-receipt')

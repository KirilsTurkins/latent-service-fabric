"""Closed, opt-in ordinary Task/monitor cases without changing the normal suite."""
from tools.phase2_operator_process import require

CASES = ('cancel-pending', 'monitor-wait')
CANCEL_CASE = '        case "cancel-pending": {\n            using var cancellation = new CancellationTokenSource();\n            var token = cancellation.Token;\n            var entered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);\n            var running = Task.Run(async () => {\n                Stage = "cancel-pending-delay";\n                var delay = Task.Delay(10000, token);\n                Incomplete(delay);\n                entered.SetResult(true);\n                await delay.ConfigureAwait(false);\n                throw new Exception("pending cancellation ignored");\n            }, token);\n            Stage = "cancel-pending-enter";\n            entered.Task.GetAwaiter().GetResult();\n            Incomplete(running);\n            Stage = "cancel-pending-cancel";\n            cancellation.Cancel();\n            try { running.GetAwaiter().GetResult(); throw new Exception("running task did not cancel"); }\n            catch (OperationCanceledException error) {\n                if (error.CancellationToken != token || !running.IsCanceled)\n                    throw new Exception("pending cancellation identity or state changed");\n            }\n            break;\n        }\n'
MONITOR_CASE = '        case "monitor-wait": {\n            object condition = new();\n            int phase = 0;\n            Task notifier;\n            lock (condition) {\n                lock (condition) {\n                    notifier = Task.Run(() => {\n                        lock (condition) {\n                            if (phase != 1) throw new Exception("monitor acquired before wait released it");\n                            phase = 2;\n                            Monitor.Pulse(condition);\n                        }\n                    });\n                    phase = 1;\n                    Stage = "monitor-wait-block";\n                    if (!Monitor.Wait(condition, 1000) || phase != 2 || !Monitor.IsEntered(condition))\n                        throw new Exception("monitor wait did not release, wake and reacquire");\n                }\n                Stage = "monitor-wait-reacquired";\n                if (!Monitor.IsEntered(condition)) throw new Exception("monitor recursion was not restored");\n            }\n            if (Monitor.IsEntered(condition)) throw new Exception("monitor remained held after both exits");\n            notifier.GetAwaiter().GetResult();\n            break;\n        }\n'


def library_source(original: str) -> str:
    require(type(original) is str and original.count('        case "context":\n') == 1
        and original.count('        case "timer-periodic-context": {\n') == 1
        and all('case "' + mode + '"' not in original for mode in CASES),
        'monitor-cancel-exact-original-task-fixture')
    return original.replace('        case "context":\n', CANCEL_CASE + '        case "context":\n') \
        .replace('        case "timer-periodic-context": {\n',
                 MONITOR_CASE + '        case "timer-periodic-context": {\n')


def expected(mode):
    require(mode in CASES, 'monitor-cancel-unknown-mode')
    return 'ordinary-tasks:' + mode + '|fresh=1'

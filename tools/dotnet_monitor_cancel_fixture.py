"""The original pending-cancellation and Monitor.Wait witness cases."""
from tools.dotnet_task_runtime_fixture import CANCEL_CASE, with_pending_cancel
from tools.phase2_operator_process import require

CASES = ('cancel-pending', 'monitor-wait')
MONITOR_CASE = '        case "monitor-wait": {\n            object condition = new();\n            int phase = 0;\n            Task notifier;\n            lock (condition) {\n                lock (condition) {\n                    notifier = Task.Run(() => {\n                        lock (condition) {\n                            if (phase != 1) throw new Exception("monitor acquired before wait released it");\n                            phase = 2;\n                            Monitor.Pulse(condition);\n                        }\n                    });\n                    phase = 1;\n                    Stage = "monitor-wait-block";\n                    if (!Monitor.Wait(condition, 1000) || phase != 2 || !Monitor.IsEntered(condition))\n                        throw new Exception("monitor wait did not release, wake and reacquire");\n                }\n                Stage = "monitor-wait-reacquired";\n                if (!Monitor.IsEntered(condition)) throw new Exception("monitor recursion was not restored");\n            }\n            if (Monitor.IsEntered(condition)) throw new Exception("monitor remained held after both exits");\n            notifier.GetAwaiter().GetResult();\n            break;\n        }\n'


def library_source(original: str) -> str:
    require(type(original) is str and original.count('        case "context":\n') == 1
        and original.count('        case "timer-periodic-context": {\n') == 1
        and all('case "' + mode + '"' not in original for mode in CASES),
        'monitor-cancel-exact-original-task-fixture')
    return with_pending_cancel(original) \
        .replace('        case "timer-periodic-context": {\n',
                 MONITOR_CASE + '        case "timer-periodic-context": {\n')


def expected(mode):
    require(mode in CASES, 'monitor-cancel-unknown-mode')
    return 'ordinary-tasks:' + mode + '|fresh=1'

"""Separate causal monitor witness; the original monitor case stays byte-identical."""
from __future__ import annotations
import re
from tools import dotnet_monitor_cancel_fixture as original
from tools.phase2_operator_process import require

CASES=('monitor-wait','monitor-cause','monitor-dispatch')
PROBE_CASE = r'''        case "monitor-cause": {
            object condition = new();
            int phase = 0;
            Task notifier;
            string waitOutcome = "not-returned";
            int observedPhase = -1;
            bool heldAfterWait = false;
            bool notifierDone = false;
            bool heldAfterInner = false;
            string joinOutcome = "not-joined";
            string Kind(Exception error) => error switch {
                SynchronizationLockException => "sync",
                ArgumentOutOfRangeException => "range",
                PlatformNotSupportedException => "unsupported",
                OperationCanceledException => "cancelled",
                InvalidOperationException => "invalid",
                _ => "other"
            };
            lock (condition) {
                lock (condition) {
                    notifier = Task.Run(() => {
                        lock (condition) {
                            if (phase != 1) throw new Exception("monitor acquired before wait released it");
                            phase = 2;
                            Monitor.Pulse(condition);
                        }
                    });
                    phase = 1;
                    Stage = "monitor-cause-block";
                    try {
                        waitOutcome = Monitor.Wait(condition, 1000) ? "signaled" : "timeout";
                    } catch (Exception error) {
                        waitOutcome = "exception-" + Kind(error);
                    }
                    observedPhase = phase;
                    heldAfterWait = Monitor.IsEntered(condition);
                    notifierDone = notifier.IsCompleted;
                    Stage = "monitor-cause-" + waitOutcome + "-p" + observedPhase
                        + "-h" + (heldAfterWait ? "1" : "0") + "-n" + (notifierDone ? "1" : "0");
                }
                heldAfterInner = Monitor.IsEntered(condition);
            }
            Stage = "monitor-cause-join";
            try {
                notifier.GetAwaiter().GetResult();
                joinOutcome = "ok";
            } catch (Exception error) {
                joinOutcome = Kind(error);
            }
            mode = "monitor-cause-" + waitOutcome + "-p" + observedPhase
                + "-h" + (heldAfterWait ? "1" : "0") + "-n" + (notifierDone ? "1" : "0")
                + "-inner" + (heldAfterInner ? "1" : "0") + "-join" + joinOutcome;
            break;
        }
'''
def _make_dispatch_probe():
    # Preserve the original causal probe exactly; add a separate pre-lock
    # marker to identify a notifier that has started by the post-wait sample.
    source = PROBE_CASE
    replacements = (
        ('case "monitor-cause":', 'case "monitor-dispatch":', 1),
        ('monitor-cause-', 'monitor-dispatch-', 4),
        ('int phase = 0;\n            Task notifier;',
         'int phase = 0;\n            int started = 0;\n            int observedStarted = -1;\n            Task notifier;', 1),
        ('notifier = Task.Run(() => {\n                        lock (condition)',
         'notifier = Task.Run(() => {\n                        Volatile.Write(ref started, 1);\n                        lock (condition)', 1),
        ('observedPhase = phase;',
         'observedStarted = Volatile.Read(ref started);\n                    observedPhase = phase;', 1),
        ('+ "-n" + (notifierDone ? "1" : "0")',
         '+ "-n" + (notifierDone ? "1" : "0") + "-s" + observedStarted', 2),
    )
    for before, after, count in replacements:
        require(source.count(before) == count, 'monitor-dispatch-probe-preimage')
        source = source.replace(before, after)
    return source


DISPATCH_PROBE_CASE = _make_dispatch_probe()

OBSERVATION = re.compile(
    r'ordinary-tasks:monitor-cause-(?:signaled|timeout|exception-(?:sync|range|unsupported|cancelled|invalid|other))'
    r'-p(?:-1|0|1|2)-h[01]-n[01]-inner[01]-join(?:ok|sync|range|unsupported|cancelled|invalid|other)\|fresh=1'
)

DISPATCH_OBSERVATION = re.compile(OBSERVATION.pattern.replace('monitor-cause-', 'monitor-dispatch-')
    .replace('-n[01]-inner', '-n[01]-s[01]-inner'))


def library_source(source: str) -> str:
    prior=original.library_source(source)
    marker='        case "timer-periodic-context": {\n'
    require(prior.count(original.MONITOR_CASE)==1 and prior.count(marker)==1
        and 'case "monitor-cause"' not in prior and 'case "monitor-dispatch"' not in prior,
        'monitor-cause-original-control')
    result=prior.replace(marker,PROBE_CASE+DISPATCH_PROBE_CASE+marker)
    require(result.count(original.MONITOR_CASE)==1,'monitor-cause-control-changed')
    return result


def expected(mode):
    require(mode=='monitor-wait','monitor-cause-fixed-control-only')
    return original.expected(mode)


def observation(row, mode='monitor-cause'):
    require(mode in ('monitor-cause', 'monitor-dispatch'), 'monitor-cause-observation-mode')
    pattern = OBSERVATION if mode == 'monitor-cause' else DISPATCH_OBSERVATION
    values=row.get('decoded')
    require(type(values) is list and len(values)==1 and type(values[0]) is dict
        and set(values[0])=={'ok'} and type(values[0]['ok']) is str
        and pattern.fullmatch(values[0]['ok']) is not None,'monitor-cause-observation-shape')
    return values[0]['ok']
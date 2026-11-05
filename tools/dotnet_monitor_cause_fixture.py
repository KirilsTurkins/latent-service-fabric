"""Separate causal monitor witness; the original monitor case stays byte-identical."""
from __future__ import annotations
import re
from tools import dotnet_monitor_cancel_fixture as original
from tools.phase2_operator_process import require

CASES=('monitor-wait','monitor-cause')
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
OBSERVATION = re.compile(
    r'ordinary-tasks:monitor-cause-(?:signaled|timeout|exception-(?:sync|range|unsupported|cancelled|invalid|other))'
    r'-p(?:-1|0|1|2)-h[01]-n[01]-inner[01]-join(?:ok|sync|range|unsupported|cancelled|invalid|other)\|fresh=1'
)


def library_source(source: str) -> str:
    prior=original.library_source(source)
    marker='        case "timer-periodic-context": {\n'
    require(prior.count(original.MONITOR_CASE)==1 and prior.count(marker)==1
        and 'case "monitor-cause"' not in prior,'monitor-cause-original-control')
    result=prior.replace(marker,PROBE_CASE+marker)
    require(result.count(original.MONITOR_CASE)==1,'monitor-cause-control-changed')
    return result


def expected(mode):
    require(mode=='monitor-wait','monitor-cause-fixed-control-only')
    return original.expected(mode)


def observation(row):
    values=row.get('decoded')
    require(type(values) is list and len(values)==1 and type(values[0]) is dict
        and set(values[0])=={'ok'} and type(values[0]['ok']) is str
        and OBSERVATION.fullmatch(values[0]['ok']) is not None,'monitor-cause-observation-shape')
    return values[0]['ok']
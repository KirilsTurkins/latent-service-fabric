"""Ordinary signed event-wait context witnesses; no application scheduler port."""
from tools.phase2_operator_process import require

CASES = ('manual-reset-context', 'manual-reset-suppressed-context',
         'manual-reset-captured-context')


def expected(mode: str) -> str:
    require(mode in CASES, 'dotnet-event-context-unknown-case')
    captured = mode == 'manual-reset-captured-context'
    suppressed = mode == 'manual-reset-suppressed-context'
    return ('ordinary-tasks:' + mode + '|pending=1|same-thread=1|setter=1'
            + '|notifications=' + ('0>13,14>0' if captured else 'none')
            + '|worker=' + ('13' if captured else '0')
            + '|caller=7|flow-suppressed=' + ('1' if suppressed else '0') + '|fresh=1')


SOURCE = r'''        case "manual-reset-context":
        case "manual-reset-suppressed-context":
        case "manual-reset-captured-context": {
            bool suppress = mode == "manual-reset-suppressed-context";
            bool capture = mode == "manual-reset-captured-context";
            Stage = "event-context-waiter-submit";
            var waiter = Task.Run(() => {
                Stage = "event-context-create";
                using var signal = new ManualResetEventSlim(false);
                int callbacks = 0, phase = 0, pendingSetter = 0, workerValue = -1;
                int notifications = 0, trace = 0;
                bool measuring = false;
                // Record, do not throw from AsyncLocal callbacks. A thrown
                // notification can terminate the runtime instead of reporting
                // which observable failed. The trace has constant storage.
                var marker = new AsyncLocal<int>(change => {
                    if (!measuring || !change.ThreadContextChanged) return;
                    notifications++;
                    if (notifications == 1 && change.PreviousValue == 0 && change.CurrentValue == 13)
                        trace = 1;
                    else if (notifications == 2 && trace == 1
                        && change.PreviousValue == 14 && change.CurrentValue == 0)
                        trace = 2;
                    else trace = -1;
                });
                marker.Value = capture ? 13 : 7;
                ExecutionContext? sibling = capture ? ExecutionContext.Capture() : null;
                int waiterThread = Environment.CurrentManagedThreadId;
                if (signal.Wait(0)) throw new InvalidOperationException("new context event already signalled");
                WaitCallback setter = _ => {
                    bool duringWait = measuring && phase == 1 && !signal.IsSet
                        && Environment.CurrentManagedThreadId == waiterThread;
                    callbacks++;
                    workerValue = marker.Value;
                    pendingSetter = duringWait && !ExecutionContext.IsFlowSuppressed()
                        && SynchronizationContext.Current == null ? 1 : -1;
                    if (capture) marker.Value = 14;
                    phase = 2;
                    // Even an invalid witness releases the waiter so that the
                    // exact post-wait assertions, not a timeout, report failure.
                    signal.Set();
                };
                AsyncFlowControl flow = default;
                if (suppress) flow = ExecutionContext.SuppressFlow();
                try {
                    // Submit only from the live waiter. Unsafe work must see
                    // the default context; safe work captures the distinct 13.
                    bool accepted = capture ? ThreadPool.QueueUserWorkItem(setter)
                        : ThreadPool.UnsafeQueueUserWorkItem(setter, null);
                    marker.Value = 7;
                    if (!accepted) throw new InvalidOperationException("context setter rejected");
                    if (phase != 0 || callbacks != 0 || signal.IsSet)
                        throw new InvalidOperationException("context setter ran before wait entry");
                    Stage = "event-context-wait";
                    measuring = true;
                    try {
                        // No dispatching call between arming and Wait. The
                        // same-thread setter must run inside this pending wait.
                        phase = 1;
                        signal.Wait();
                    } finally { measuring = false; }
                    Stage = "event-context-pending-result";
                    if (phase != 2 || pendingSetter != 1 || !signal.IsSet || callbacks != 1)
                        throw new InvalidOperationException("pending context wait or setter lost");
                    Stage = "event-context-caller-restoration";
                    if (marker.Value != 7 || ExecutionContext.IsFlowSuppressed() != suppress
                        || SynchronizationContext.Current != null)
                        throw new InvalidOperationException("event caller context changed");
                    Stage = "event-context-notifications";
                    // The unsafe setter produces no user transitions. The safe
                    // setter retains exactly its original entry/reset pair;
                    // suppressing all notifications is not an acceptable fix.
                    if (workerValue != (capture ? 13 : 0)
                        || notifications != (capture ? 2 : 0) || trace != (capture ? 2 : 0))
                        throw new InvalidOperationException("event context notification mismatch");
                    phase = 3;
                    signal.Reset();
                    if (signal.Wait(0)) throw new InvalidOperationException("context event reset lost");
                } finally {
                    if (suppress) flow.Undo();
                    marker.Value = 0;
                }
                if (capture) {
                    Stage = "event-context-capture-immutability";
                    if (sibling == null) throw new InvalidOperationException("sibling capture missing");
                    ExecutionContext.Run(sibling, _ => {
                        if (marker.Value != 13) throw new InvalidOperationException("captured values mutated");
                    }, null);
                    if (marker.Value != 0) throw new InvalidOperationException("capture reentry escaped");
                }
            });
            Stage = "event-context-waiter-join";
            waiter.GetAwaiter().GetResult();
            if (SynchronizationContext.Current != null) throw new InvalidOperationException("custom context escaped");
            return "ordinary-tasks:" + mode + "|pending=1|same-thread=1|setter=1"
                + "|notifications=" + (capture ? "0>13,14>0" : "none")
                + "|worker=" + (capture ? "13" : "0")
                + "|caller=7|flow-suppressed=" + (suppress ? "1" : "0") + "|fresh=1";
        }
'''

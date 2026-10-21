package outside.diagnostics;

import java.util.Timer;
import java.util.TimerTask;
import outside.diagnosticsdata.Core;

/** Default ordinary Timer callback and constructor, without an injected runtime. */
public final class Library {
    private static int calls;
    public Library() { new Core(); }
    private static final class State {
        boolean finished;
        int answer;
        Throwable failure;
    }
    public String run(String mode) {
        if (++calls != 1) throw new IllegalStateException("diagnostics-activation-state-leaked");
        if (mode.equals("init") || mode.equals("fresh"))
            return "diagnostics|" + mode + "|" + Core.state(2) + "|fallback=42|fresh=1";
        if (mode.equals("init-trap")) {
            Core.initializationFailure();
            throw new IllegalStateException("diagnostics-initializer-returned");
        }
        if (!mode.equals("callback") && !mode.equals("callback-trap"))
            throw new IllegalArgumentException("diagnostics-unknown-mode");
        State state = new State();
        Timer timer = new Timer("diagnostics-default", true);
        try {
            timer.schedule(new TimerTask() {
                @Override public void run() {
                    try {
                        if (mode.equals("callback-trap")) Core.uncaught();
                        else state.answer = Core.fallback();
                    } catch (Throwable error) { state.failure = error; }
                    finally {
                        synchronized (state) { state.finished = true; state.notifyAll(); }
                    }
                }
            }, 1);
            synchronized (state) {
                while (!state.finished) {
                    try { state.wait(); }
                    catch (InterruptedException error) { throw new IllegalStateException("diagnostics-interrupted", error); }
                }
            }
            // Relay the original callback failure only after its finally.
            if (state.failure != null) throw new IllegalStateException("diagnostics-callback-failed", state.failure);
            if (state.answer != 42) throw new IllegalStateException("diagnostics-callback-answer");
            return "diagnostics|callback|" + Core.state(3) + "|fallback=42|finally=1|fresh=1";
        } finally { timer.cancel(); }
    }
}

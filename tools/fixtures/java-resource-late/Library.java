package outside.resourceruntime;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Timer;
import java.util.TimerTask;
import outside.resourceruntimedata.Data;

/** Ordinary already-entered TimerTask work; no application runtime bridge. */
public final class Library {
    private static int visits;
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private Library() { }
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("resource-late-observable");
    }
    private static final class Shared {
        boolean entered, cancelled, release;
        int completed, closed;
        Throwable failure;
    }
    private static void waitOn(Shared state) {
        try { state.wait(); }
        catch (InterruptedException error) { throw new IllegalStateException("resource-late-interrupted", error); }
    }
    private static void facilities(Data data, char marker) {
        try (InputStream text = Data.class.getResourceAsStream("utf8.txt")) {
            require(text != null && "Gr\u00fc\u00dfe\0\u96ea\n".equals(new String(text.readAllBytes(), StandardCharsets.UTF_8)));
        } catch (java.io.IOException error) { throw new IllegalStateException("resource-late-text", error); }
        data.verifyEmpty();
        long before = System.nanoTime();
        long wall = System.currentTimeMillis();
        byte[] entropy = new byte[8];
        new SecureRandom().nextBytes(entropy);
        require(before >= 0 && System.nanoTime() >= before && wall > 0x1_0000_0000L);
        java.util.Arrays.fill(entropy, (byte) 0);
        data.close();
        // Exactly one standard, synchronous completion record, after reads/close.
        System.out.print(marker); System.out.flush(); require(!System.out.checkError());
    }
    public static String run(String mode) {
        require(++visits == 1 && local.get() == null);
        local.set("root");
        Data data = new Data();
        if (mode.equals("fresh")) {
            try (data) {
                require(Data.read(data.first) == 0 && Data.read(data.first) == 255);
                require(Data.read(data.second) == 0 && Data.read(data.second) == 255);
                Data.remainder(data.first); Data.remainder(data.second);
                facilities(data, 'F');
                return "resource-late|fresh|readers=2|binary=00ff80410d0a|text=1|empty=1|entropy=8|wall64=1|closed=1";
            } finally { local.remove(); }
        }
        require(mode.equals("late"));
        Shared state = new Shared();
        Timer timer = new Timer("resource-late", true);
        TimerTask task = new TimerTask() {
            @Override public void run() {
                try {
                    require(local.get() == null); local.set("callback");
                    require(Data.read(data.first) == 0 && Data.read(data.first) == 255);
                    require(Data.read(data.second) == 0);
                    synchronized (state) {
                        state.entered = true; state.notifyAll();
                        while (!state.release) waitOn(state);
                        require(state.cancelled && state.completed == 0);
                    }
                    require("callback".equals(local.get()));
                    Data.remainder(data.first);
                    require(Data.read(data.second) == 255); Data.remainder(data.second);
                    facilities(data, 'L');
                    synchronized (state) { state.completed++; }
                } catch (Throwable error) {
                    synchronized (state) { state.failure = error; }
                } finally {
                    try { data.close(); }
                    catch (Throwable error) { synchronized (state) { if (state.failure == null) state.failure = error; } }
                    finally {
                        local.remove();
                        synchronized (state) { state.closed++; state.notifyAll(); }
                    }
                }
            }
        };
        try {
            timer.schedule(task, 1);
            synchronized (state) {
                while (!state.entered && state.failure == null) waitOn(state);
                require(state.failure == null && state.completed == 0 && state.closed == 0);
                require(!task.cancel()); timer.cancel();
                require(state.completed == 0 && state.closed == 0);
                state.cancelled = true; state.release = true; state.notifyAll();
                while (state.closed == 0) waitOn(state);
                if (state.failure != null) throw new IllegalStateException("resource-late-callback", state.failure);
                require(state.completed == 1 && state.closed == 1 && "root".equals(local.get()));
            }
            return "resource-late|cancel=false|entered=1|completed=1|readers=2|binary=00ff80410d0a|text=1|empty=1|entropy=8|wall64=1|closed=1";
        } finally { timer.cancel(); data.close(); local.remove(); }
    }
}

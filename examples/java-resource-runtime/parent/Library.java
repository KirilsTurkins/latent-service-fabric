package outside.resourceruntime;

import java.security.SecureRandom;
import java.util.Timer;
import java.util.TimerTask;
import outside.resourceruntimedata.Data;

public final class Library {
    private static int visits;
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private Library() { }

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("resource-runtime-observable");
    }

    private static void observations() {
        long before = System.nanoTime();
        long wall = System.currentTimeMillis();
        byte[] bytes = new byte[8];
        new SecureRandom().nextBytes(bytes);
        require(System.nanoTime() >= before && before >= 0 && wall > 0x1_0000_0000L);
        java.util.Arrays.fill(bytes, (byte) 0);
    }

    private static boolean writeLog(String name) {
        // Correlation is host-derived and charged too. One ASCII byte keeps
        // every existing activation's complete record inside the 256-byte cap.
        System.out.print(name.charAt(0));
        System.out.flush();
        return System.out.checkError();
    }

    private static void facilities(String name) {
        observations();
        require(!writeLog(name));
    }

    private static void parallelLog(Shared state, String name) {
        // Only the two log expectations serialize. Resource readers, clocks,
        // RNG, ThreadLocal state and the callback rendezvous remain independent.
        synchronized (state) {
            require(state.logWrites < 2);
            require(writeLog(name) == (state.logWrites == 1));
            state.logWrites++;
        }
    }

    private static final class Shared {
        int arrived;
        int completed;
        int first;
        int second;
        int logWrites;
        Throwable failure;
    }

    private static TimerTask callback(Shared state, Runnable action) {
        return new TimerTask() {
            @Override public void run() {
                try { action.run(); }
                catch (Throwable error) {
                    synchronized (state) { state.failure = error; state.notifyAll(); }
                    throw error;
                } finally { synchronized (state) { state.notifyAll(); } }
            }
        };
    }

    private static void waitOn(Shared state) {
        try { state.wait(); }
        catch (InterruptedException error) { throw new IllegalStateException("resource-runtime-interrupted", error); }
    }

    private static void arrive(Shared state, String name) {
        require(local.get() == null);
        local.set(name);
        synchronized (state) {
            state.arrived++;
            state.notifyAll();
            while (state.arrived != 2 && state.failure == null) waitOn(state);
            require(state.failure == null && name.equals(local.get()));
        }
    }

    private static String parallel(Data data) {
        Shared state = new Shared();
        local.set("root");
        require(Data.read(data.first) == 0 && Data.read(data.second) == 0);
        Timer first = new Timer("resource-first", true);
        Timer second = new Timer("resource-second", true);
        first.schedule(callback(state, () -> {
            arrive(state, "first");
            observations();
            parallelLog(state, "first");
            state.first = Data.read(data.first);
            require(state.first == 255);
            Data.remainder(data.first);
            data.closeFirst();
            synchronized (state) { state.completed++; state.notifyAll(); }
        }), 1);
        second.schedule(callback(state, () -> {
            arrive(state, "second");
            observations();
            parallelLog(state, "second");
            state.second = Data.read(data.second);
            require(state.second == 255);
            Data.remainder(data.second);
            data.verifyEmpty();
            synchronized (state) { state.completed++; state.notifyAll(); }
        }), 2);
        synchronized (state) {
            while (state.completed != 2 && state.failure == null) waitOn(state);
        }
        first.cancel(); second.cancel();
        require(state.failure == null && state.logWrites == 2 && "root".equals(local.get()));
        return "resource-runtime|parallel=" + state.first + ":" + state.second + "|callbacks=2|logs=accepted:sticky-error|fresh=1";
    }

    private static String fresh(Data data, String name) {
        require(Data.read(data.first) == 0 && Data.read(data.first) == 255);
        Data.remainder(data.first);
        data.closeFirst();
        require(Data.read(data.second) == 0 && Data.read(data.second) == 255);
        Data.remainder(data.second);
        data.verifyEmpty();
        facilities(name);
        return "resource-runtime|" + name + "=00ff80410d0a|empty=0|fresh=1";
    }

    private static String callbackFailure(Data data) {
        Shared state = new Shared();
        boolean[] caught = {false};
        Timer timer = new Timer("resource-failure", true);
        timer.schedule(callback(state, () -> {
            boolean armed = false;
            try {
                require(Data.read(data.first) == 0);
                facilities("callback-error");
                armed = true;
                throw new IllegalStateException("resource-callback-error");
            } catch (IllegalStateException error) {
                require(armed && error.getClass() == IllegalStateException.class);
                caught[0] = true;
            } finally {
                data.close();
                timer.cancel();
            }
            synchronized (state) { state.completed++; state.notifyAll(); }
        }), 1);
        synchronized (state) {
            while (state.completed != 1 && state.failure == null) waitOn(state);
        }
        require(state.failure == null && caught[0]);
        try (Data fresh = new Data()) {
            require(Data.read(fresh.first) == 0 && Data.read(fresh.second) == 0);
            require(Data.read(fresh.first) == 255 && Data.read(fresh.second) == 255);
            Data.remainder(fresh.first); Data.remainder(fresh.second); fresh.verifyEmpty();
        }
        return "resource-runtime|callback-error=IllegalStateException|fresh=1";
    }

    public static String run(String mode) {
        require(++visits == 1);
        Data data = new Data();
        if (mode.equals("pending")) {
            Timer timer = new Timer("resource-accepted", true);
            timer.schedule(new TimerTask() {
                @Override public void run() {
                    try {
                        require(Data.read(data.first) == 0);
                        facilities("accepted");
                    } finally { data.close(); timer.cancel(); }
                }
            }, 60_000);
            facilities("pending-accepted");
            return "resource-runtime|accepted-root-return";
        }
        try (data) {
            if (mode.equals("trap")) throw new IllegalStateException("resource-root-trap");
            if (mode.equals("parallel")) return parallel(data);
            if (mode.equals("callback-error")) return callbackFailure(data);
            if (mode.equals("fresh")) return fresh(data, "fresh");
            if (mode.equals("clear")) {
                boolean[] fired = {false};
                Timer timer = new Timer("resource-clear", true);
                TimerTask task = new TimerTask() {
                    @Override public void run() { fired[0] = true; require(Data.read(data.first) == 0); }
                };
                timer.schedule(task, 60_000);
                require(task.cancel()); timer.purge(); timer.cancel();
                try { Thread.sleep(3); }
                catch (InterruptedException error) { throw new IllegalStateException(error); }
                require(!fired[0]);
                return fresh(data, "clear");
            }
            throw new IllegalArgumentException("resource-runtime-mode");
        }
    }
}

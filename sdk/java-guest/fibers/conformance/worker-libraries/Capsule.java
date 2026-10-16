package dev.latent.app;

import cn.hutool.core.thread.ThreadUtil;
import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import org.apache.commons.lang3.concurrent.CallableBackgroundInitializer;

public final class Capsule {
    private static volatile int started, progress, hutoolResult;
    private static volatile Throwable workerFailure;
    private static volatile Thread hutoolThread;
    private static final Object startGate = new Object();
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("published-worker-observable");
    }
    private static void hostWait() {
        var result = Bindings.LatentRuntimeActivation.waitFor(new Unsigned64(250_000_000L), Option.none());
        require(!result.isError());
    }
    private static int initialize(boolean fail) {
        require(local.get() == null);
        local.set("commons-worker");
        synchronized (startGate) { started |= 1; }
        hostWait();
        require(progress == 42 && "commons-worker".equals(local.get()));
        if (fail) throw new IllegalArgumentException("published-worker-error");
        return 42;
    }
    private static void hutool(boolean interrupted) {
        try {
            require(local.get() == null);
            local.set("hutool-worker");
            hutoolThread = Thread.currentThread();
            synchronized (startGate) { started |= 2; }
            hostWait();
            require(progress == 42 && "hutool-worker".equals(local.get()));
            require(Thread.interrupted() == interrupted);
            hutoolResult = 42;
        } catch (Throwable failure) { workerFailure = failure; }
    }
    private static void started(int mask) {
        while ((started & mask) != mask) {
            if (workerFailure != null) throw new IllegalStateException(workerFailure);
            Thread.yield();
        }
    }
    private static Thread startHutool(boolean interrupted) {
        ThreadUtil.execAsync(() -> hutool(interrupted), false);
        started(2);
        return hutoolThread;
    }
    public Long run(Long mode) {
        started = progress = hutoolResult = 0;
        workerFailure = null;
        hutoolThread = null;
        local.set("root");
        try {
            if (mode == 0) {
                var initializer = new CallableBackgroundInitializer<Integer>(() -> initialize(false));
                require(initializer.getExternalExecutor() == null && initializer.start());
                started(1); progress = 42;
                require(initializer.get() == 42 && !initializer.start());
            } else if (mode == 1) {
                Thread worker = startHutool(false);
                started(2); progress = 42;
                worker.join();
                require(hutoolResult == 42 && !worker.isAlive());
            } else if (mode == 2) {
                var initializer = new CallableBackgroundInitializer<Integer>(() -> initialize(false));
                require(initializer.getExternalExecutor() == null && initializer.start());
                Thread worker = startHutool(false);
                started(3); progress = 42;
                require(initializer.get() == 42);
                worker.join();
                require(hutoolResult == 42 && !worker.isAlive());
            } else if (mode == 3) {
                var initializer = new CallableBackgroundInitializer<Integer>(() -> initialize(true));
                require(initializer.getExternalExecutor() == null && initializer.start());
                Thread worker = startHutool(true);
                started(3); progress = 42;
                worker.interrupt();
                boolean originalError = false;
                try { initializer.get(); }
                catch (IllegalArgumentException error) {
                    originalError = "published-worker-error".equals(error.getMessage());
                }
                require(originalError);
                worker.join();
                require(hutoolResult == 42 && !worker.isAlive());
            } else throw new IllegalArgumentException();
            if (workerFailure != null) throw new IllegalStateException(workerFailure);
            require("root".equals(local.get()));
            return 42L;
        } catch (InterruptedException | org.apache.commons.lang3.concurrent.ConcurrentException error) {
            throw new IllegalStateException(error);
        }
    }
}

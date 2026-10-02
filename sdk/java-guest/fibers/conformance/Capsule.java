package dev.latent.app;
public final class Capsule {
    private static volatile boolean ready;
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    public Long run(Long mode) {
        local.set("root");
        Thread worker = new Thread(() -> {
            if (local.get() != null) throw new IllegalStateException("thread-local-leaked");
            local.set("worker");
            try { Thread.sleep(20); } catch (InterruptedException error) { throw new IllegalStateException(error); }
            ready = true;
        });
        if (worker.isAlive()) throw new IllegalStateException("unstarted-thread-alive");
        worker.start();
        while (!ready) { }
        try { worker.join(); } catch (InterruptedException error) { throw new IllegalStateException(error); }
        if (worker.isAlive() || !"root".equals(local.get())) throw new IllegalStateException("join-or-local");
        return 42L;
    }
}

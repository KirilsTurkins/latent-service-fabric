package dev.latent.guest.runtime.concurrent;

/** Host source control only. Component controls use the actual managed SDK pool. */
public final class Executors {
    public static java.util.concurrent.ExecutorService newCachedThreadPool() {
        return java.util.concurrent.Executors.newCachedThreadPool();
    }
}

package dev.latent.app;

import com.github.kevinsawicki.http.HttpRequest;
import dev.latent.generated.Bindings;
import java.io.InputStream;
import java.util.Timer;
import java.util.TimerTask;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Ordinary published HTTP calls beneath the maintained Java fiber-I/O profile. */
public final class Capsule implements Bindings.Exports {
    private static int calls;
    private static volatile int entered;
    private static volatile int completed;
    private static volatile int timerFired;
    private static volatile int childStatus;
    private static volatile String childContext;
    private static final ThreadLocal<String> context = new ThreadLocal<>();

    private static int get(String endpoint) {
        HttpRequest request = HttpRequest.get(endpoint).followRedirects(false);
        try { return request.code(); }
        finally { request.disconnect(); }
    }

    private static Thread pending(String endpoint) {
        return new Thread(() -> {
            context.set("child");
            entered = 1;
            childStatus = get(endpoint + "/conformance/hold/headers");
            childContext = context.get();
            completed = 1;
        });
    }

    public String run(Long which, String endpoint) {
        int invocation = ++calls;
        if (which == 7) return invocation + ":fresh:" + get(endpoint + "/conformance/json")
            + ":" + entered + ":" + completed;
        context.set("root");
        try {
            if (which == 1) {
                ExecutorService first = Executors.newSingleThreadExecutor();
                ExecutorService second = Executors.newSingleThreadExecutor();
                try {
                    Future<Integer> blocked = first.submit(() -> {
                        HttpRequest request = HttpRequest.get(endpoint + "/conformance/body/partial")
                            .followRedirects(false);
                        try (InputStream input = request.stream()) {
                            byte[] prefix = new byte[5];
                            int used = 0;
                            while (used != prefix.length) {
                                int n = input.read(prefix, used, prefix.length - used);
                                if (n <= 0) throw new IllegalStateException("missing-body-prefix");
                                used += n;
                            }
                            if (!new String(prefix, java.nio.charset.StandardCharsets.UTF_8).equals("first"))
                                throw new IllegalStateException("wrong-body-prefix");
                            entered = 1;
                            int size = used;
                            byte[] part = new byte[1024];
                            for (int n; (n = input.read(part)) != -1;) size += n;
                            completed = 1;
                            return size;
                        } finally { request.disconnect(); }
                    });
                    while (entered == 0) Thread.yield();
                    Future<Integer> sibling = second.submit(() -> {
                        int wasPending = completed == 0 ? 1 : 0;
                        if (get(endpoint + "/conformance/json") != 200)
                            throw new IllegalStateException("sibling-http-status");
                        return wasPending;
                    });
                    int independent = sibling.get();
                    int size = blocked.get();
                    return invocation + ":queues:" + independent + ":" + size + ":" + completed;
                } finally {
                    first.shutdown();
                    second.shutdown();
                }
            }
            Thread child = pending(endpoint);
            child.start();
            if (which == 2) return invocation + ":root-return:" + completed;
            if (which == 3) throw new IllegalStateException("owned-root-failure");
            if (which == 6) {
                while (true) Thread.yield();
            }
            if (which == 4 || which == 5) {
                child.join();
                return invocation + ":unexpected-release";
            }
            if (which != 0) throw new IllegalArgumentException("unknown-lifecycle-case");
            Timer timer = new Timer();
            try {
                timer.schedule(new TimerTask() {
                    public void run() { timerFired = 1; }
                }, 25);
                while (entered == 0 || timerFired == 0) Thread.yield();
                int wasPending = completed == 0 ? 1 : 0;
                int siblingStatus = get(endpoint + "/conformance/json");
                child.join();
                return invocation + ":headers:" + siblingStatus + ":" + wasPending + ":"
                    + timerFired + ":" + childStatus + ":" + context.get() + ":" + childContext;
            } finally { timer.cancel(); }
        } catch (RuntimeException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException("ordinary-java-http-lifecycle-failed", error);
        }
    }
}

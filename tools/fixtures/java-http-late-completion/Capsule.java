package dev.latent.app;

import com.github.kevinsawicki.http.HttpRequest;
import dev.latent.generated.Bindings;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/** Late accepted work stays owned after logical cancellation until physical return. */
public final class Capsule implements Bindings.Exports {
    private static int calls;
    private static volatile int prefixReady;
    private static volatile int physicallyReturned;
    private static volatile int received;
    private static volatile Throwable callbackFailure;

    private static String receive(String endpoint) {
        HttpRequest request = HttpRequest.get(endpoint + "/conformance/body/partial");
        try {
            request.receive(new OutputStream() {
                public void write(int value) throws IOException {
                    String prefix = "first-second-";
                    int expected = received < prefix.length() ? prefix.charAt(received) : 'x';
                    if (value != expected || received >= 4109) throw new IOException("late-body-byte-mismatch");
                    received++;
                    if (received >= 5) prefixReady = 1;
                }
                public void write(byte[] bytes, int offset, int length) throws IOException {
                    for (int index = 0; index < length; index++) write(bytes[offset + index] & 255);
                }
            });
            if (received != 4109) throw new IllegalStateException("late-body-length");
            return "late-http-result";
        } catch (Throwable error) {
            callbackFailure = error;
            throw error;
        } finally {
            request.disconnect();
            physicallyReturned = 1;
        }
    }

    private static void cancelled(Future<String> future) throws Exception {
        if (!future.isCancelled() || !future.isDone()) throw new IllegalStateException("future-not-cancelled");
        try { future.get(); }
        catch (CancellationException expected) { return; }
        throw new IllegalStateException("cancelled-future-produced-a-value");
    }

    private static long results() {
        // Read-only test observation. This does not provide HTTP, an executor,
        // a replacement completion path or authority to the published library.
        var observed = Bindings.LatentRuntimeActivation.observe();
        if (observed.isError()) throw new IllegalStateException("runtime-owner-observation-unavailable");
        return observed.value().results();
    }

    private static void cancellationMarker(String endpoint, String kind, long retained) throws IOException {
        HttpURLConnection connection = (HttpURLConnection)new URL(endpoint + "/conformance/echo").openConnection();
        try {
            connection.setDoOutput(true);
            byte[] value = (kind + ":cancelled:results:" + retained).getBytes(StandardCharsets.US_ASCII);
            connection.setFixedLengthStreamingMode(value.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(value); }
            if (connection.getResponseCode() != 200) throw new IOException("cancel-marker-status");
            try (InputStream input = connection.getInputStream()) {
                byte[] chunk = new byte[1024];
                while (input.read(chunk) != -1) { }
            }
        } finally { connection.disconnect(); }
    }

    public String run(Long which, String endpoint) {
        if (which == null || which < 0 || which > 2) throw new IllegalArgumentException("unknown-late-case");
        int invocation = ++calls;
        if (which == 2) {
            HttpRequest request = HttpRequest.get(endpoint + "/conformance/json");
            try { return invocation + ":fresh:" + request.code() + ":" + prefixReady + ":" + physicallyReturned; }
            finally { request.disconnect(); }
        }
        ExecutorService executor = null;
        try {
            String kind = which == 0 ? "future-task" : "completable-default";
            Future<String> future;
            if (which == 0) {
                executor = Executors.newSingleThreadExecutor();
                future = executor.submit(() -> receive(endpoint));
            } else future = CompletableFuture.supplyAsync(() -> receive(endpoint));
            while (prefixReady == 0 && physicallyReturned == 0) Thread.yield();
            if (prefixReady != 1 || physicallyReturned != 0) throw new IllegalStateException("no-pending-body");
            if (!future.cancel(false)) throw new IllegalStateException("logical-cancellation-refused");
            cancelled(future);
            long retained = results();
            if (retained != 1) throw new IllegalStateException("cancelled-running-result-owner-lost");
            // The controlled peer can release the real suffix only after this
            // ordinary POST proves logical cancellation and retained ownership.
            cancellationMarker(endpoint, kind, retained);
            while (physicallyReturned == 0) Thread.yield();
            if (callbackFailure != null) throw new IllegalStateException("late-http-callback-failed", callbackFailure);
            cancelled(future);
            if (executor != null) {
                executor.shutdown();
                if (!executor.awaitTermination(1, TimeUnit.SECONDS)) throw new IllegalStateException("late-worker-not-retired");
            }
            // Supplier finally may be scheduled immediately before its Action
            // finally. Observe at most64 times under the original root budget;
            // no operation is retried and no result is inferred from a sleep.
            long after = -1;
            for (int attempt = 0; attempt < 64; attempt++) {
                after = results();
                if (after == 0) break;
                Thread.yield();
            }
            if (after != 0) throw new IllegalStateException("late-result-owner-retained");
            cancelled(future);
            return invocation + ":late:" + kind + ":" + retained + ":" + after
                + ":" + physicallyReturned + ":true:" + received;
        } catch (Exception error) {
            throw new IllegalStateException("ordinary-java-late-completion-failed", error);
        } finally {
            if (executor != null) executor.shutdown();
        }
    }
}

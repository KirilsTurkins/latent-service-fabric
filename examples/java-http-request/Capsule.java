package dev.latent.app;

import com.github.kevinsawicki.http.HttpRequest;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.InputStream;

/** Unchanged published client; its ordinary default connection factory is used. */
public final class Capsule implements Bindings.Exports {
    private static int calls;

    public String run(Long which, String endpoint) {
        int invocation = ++calls;
        HttpRequest request = null;
        try {
            request = which == 1 ? HttpRequest.post(endpoint) : HttpRequest.get(endpoint);
            if (which == 1) request.contentType("application/octet-stream").contentLength(4)
                .send(new byte[] {0, 1, 2, 3});
            if (which == 3) request.authorization("must-not-leave-guest");
            int status = request.code();
            if (which != 2) return invocation + ":" + status + ":" + request.body();
            try (InputStream input = request.stream()) {
                return invocation + ":early:" + input.read(new byte[4]);
            }
        } catch (Exception failure) {
            Throwable cause = failure;
            for (int n = 0; n < 8; n++) {
                if (cause instanceof HttpFailure typed) return invocation + ":transport:" + typed.code();
                if (cause.getCause() == null || cause.getCause() == cause) break;
                cause = cause.getCause();
            }
            return invocation + ":io-error";
        } finally {
            if (request != null) request.disconnect();
        }
    }
}

package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Ordinary standard APIs; no application HTTP transport or SDK request. */
public final class Capsule implements Bindings.Exports {
    private static int calls;

    public String run(Long which, String endpoint) {
        int invocation = ++calls;
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) (which == 4
                ? new URL(endpoint).openConnection(java.net.Proxy.NO_PROXY)
                : new URL(endpoint).openConnection());
            if (which == 1) {
                connection.setRequestMethod("POST");
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/octet-stream");
                connection.setFixedLengthStreamingMode(4L);
                try (var output = connection.getOutputStream()) {
                    output.write(new byte[] {0, 1, 2, 3});
                }
            }
            if (which == 3) connection.setRequestProperty("Authorization", "must-not-leave-guest");
            int status = connection.getResponseCode();
            try (InputStream input = status >= 400 ? connection.getErrorStream() : connection.getInputStream()) {
                var result = new ByteArrayOutputStream();
                byte[] chunk = new byte[4];
                for (;;) {
                    int size = input.read(chunk);
                    if (size < 0) break;
                    result.write(chunk, 0, size);
                    if (result.size() > 262144) throw new IOException("application-body-limit");
                    if (which == 2) return invocation + ":early:" + size;
                }
                return invocation + ":" + status + ":" + new String(result.toByteArray(), StandardCharsets.UTF_8);
            }
        } catch (HttpFailure failure) {
            return invocation + ":transport:" + failure.code();
        } catch (IOException failure) {
            return invocation + ":io-error";
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}

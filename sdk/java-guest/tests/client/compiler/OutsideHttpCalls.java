package dev.latent.guest.client.compiler;

import java.net.HttpURLConnection;

/** Ordinary compiled caller; no SDK transport, executor or dependency rewrite. */
public final class OutsideHttpCalls {
    public static long read(HttpURLConnection connection) {
        connection.setFixedLengthStreamingMode(2L);
        return connection.getContentLengthLong() + connection.getHeaderFieldLong("X-Long", -1L);
    }
}

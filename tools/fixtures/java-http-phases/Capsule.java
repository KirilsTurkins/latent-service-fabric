package dev.latent.app;

import com.goebl.david.Response;
import com.goebl.david.Webb;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import org.json.JSONObject;

/** Ordinary default client and finite standard per-operation timeout controls. */
public final class Capsule implements Bindings.Exports {
    private static int calls;

    public String run(Long which, String endpoint) {
        if (which == null || which < 0 || which > 9) throw new IllegalArgumentException("unknown-phase-case");
        int invocation = ++calls;
        if (which == 0) {
            // Do not replace the published library's nonzero phase defaults.
            Response<JSONObject> response = Webb.create().get(endpoint + "/conformance/json")
                .followRedirects(false).asJsonObject();
            return invocation + ":default-webb:" + response.getStatusCode() + ":"
                + response.getResponseMessage() + ":" + response.getBody().getInt("id");
        }
        boolean pendingHeaders = which == 2 || which == 4 || which == 5;
        String path = pendingHeaders ? "/conformance/hold/headers"
            : which == 3 ? "/conformance/body/partial" : "/conformance/json";
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection)new URL(endpoint + path).openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(which == 7 ? 100 : which >= 8 ? 5000 : 1000);
            connection.setReadTimeout(which == 2 || which == 3 ? 100 : 5000);
            if (which == 1 || which == 6) connection.setReadTimeout(1000);
            if (which >= 7) {
                connection.connect();
                throw new IllegalStateException("pending-connect-case-returned");
            }
            int status = connection.getResponseCode();
            if (which == 3) {
                try (InputStream input = connection.getInputStream()) {
                    byte[] prefix = new byte[5];
                    int used = 0;
                    while (used != prefix.length) {
                        int count = input.read(prefix, used, prefix.length - used);
                        if (count <= 0) throw new IllegalStateException("missing-body-prefix");
                        used += count;
                    }
                    if (!new String(prefix, java.nio.charset.StandardCharsets.UTF_8).equals("first"))
                        throw new IllegalStateException("wrong-body-prefix");
                    input.read();
                    throw new IllegalStateException("body-timeout-did-not-occur");
                }
            }
            if (pendingHeaders) throw new IllegalStateException("pending-header-case-returned");
            try (InputStream input = connection.getInputStream()) {
                int count = 0;
                for (int value; (value = input.read()) != -1;) count++;
                return invocation + ":explicit:" + status + ":" + connection.getResponseMessage()
                    + ":" + count + ":" + connection.getConnectTimeout() + ":" + connection.getReadTimeout();
            }
        } catch (SocketTimeoutException timeout) {
            if (which == 7) {
                if (!"http-connect-timeout".equals(timeout.getMessage()) || timeout.getCause() != null)
                    throw new IllegalStateException("wrong-connect-phase-outcome", timeout);
                return invocation + ":connect-timeout:false";
            }
            if (which != 2 && which != 3) throw new IllegalStateException("unexpected-phase-timeout", timeout);
            if (!"http-read-timeout".equals(timeout.getMessage()))
                throw new IllegalStateException("wrong-read-phase-outcome", timeout);
            boolean uncertain = timeout.getCause() instanceof HttpFailure
                && ((HttpFailure)timeout.getCause()).code().equals("uncertain");
            if (uncertain != (which == 2)) throw new IllegalStateException("wrong-phase-uncertainty", timeout);
            return invocation + ":read-timeout:" + (which == 2 ? "headers" : "body") + ":" + uncertain;
        } catch (java.io.IOException error) {
            throw new IllegalStateException("ordinary-java-phase-io-failed", error);
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}

package dev.latent.app;

import com.github.kevinsawicki.http.HttpRequest;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
import org.json.JSONObject;

/** Optional ordinary library SPI; this is not the no-injection default programme. */
public final class Capsule implements Bindings.Exports {
    private static int invocations;
    private static int factoryCalls;

    private static final class OrdinaryFactory implements HttpRequest.ConnectionFactory {
        private final boolean forbiddenCredential;
        OrdinaryFactory(boolean forbiddenCredential) { this.forbiddenCredential = forbiddenCredential; }
        @Override public HttpURLConnection create(URL target) throws IOException {
            factoryCalls++;
            HttpURLConnection connection = (HttpURLConnection)target.openConnection();
            connection.setRequestProperty("x-conformance", "optional-spi");
            if (forbiddenCredential)
                connection.setRequestProperty("authorization", "not-a-provider-credential");
            return connection;
        }
        @Override public HttpURLConnection create(URL target, Proxy proxy) throws IOException {
            if (proxy != Proxy.NO_PROXY)
                throw new UnsupportedOperationException("optional-spi-proxy-not-qualified");
            return create(target);
        }
    }

    public String run(Long which, String endpoint) {
        if (which == null || which < 0 || which > 4)
            throw new IllegalArgumentException("unknown-spi-case");
        int invocation = ++invocations;
        if (which != 1) HttpRequest.setConnectionFactory(new OrdinaryFactory(which == 3));
        if (which == 4) HttpRequest.setConnectionFactory(null);
        HttpRequest request = null;
        try {
            request = HttpRequest.get(endpoint + "/conformance/json");
            int status = request.code();
            int id = new JSONObject(request.body()).getInt("id");
            if (which == 2 || which == 3) throw new IllegalStateException("spi-denial-did-not-occur");
            return invocation + ":spi:" + status + ":" + id + ":" + factoryCalls;
        } catch (Exception failure) {
            Throwable cause = failure;
            for (int depth = 0; depth < 8; depth++) {
                if (cause instanceof HttpFailure typed)
                    return invocation + ":spi-error:" + typed.code() + ":" + factoryCalls;
                if (cause.getCause() == null || cause.getCause() == cause) break;
                cause = cause.getCause();
            }
            throw new IllegalStateException("unexpected-optional-spi-failure", failure);
        } finally {
            if (request != null) request.disconnect();
        }
    }
}

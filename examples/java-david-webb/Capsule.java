package dev.latent.app;

import com.goebl.david.Request;
import com.goebl.david.Response;
import com.goebl.david.Webb;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import java.io.InputStream;
import org.json.JSONArray;
import org.json.JSONObject;

/** Ordinary published factory and its unchanged transitive JSON implementation. */
public final class Capsule implements Bindings.Exports {
    private static int calls;

    private static void checkMessage(Response<?> response) {
        if (response.getResponseMessage() != null) {
            throw new IllegalStateException("typed provider supplies no wire reason phrase");
        }
    }

    public String run(Long which, String endpoint) {
        int invocation = ++calls;
        try {
            Webb client = Webb.create();
            Request request = which == 1 ? client.post(endpoint) : client.get(endpoint);
            request.connectTimeout(0).readTimeout(0).followRedirects(false);
            if (which == 1) request.body(new byte[] {0, 1, 2, 3});
            if (which == 3) request.header("Authorization", "must-not-leave-guest");
            if (which == 2) {
                Response<InputStream> response = request.asStream();
                checkMessage(response);
                try (InputStream body = response.getBody()) {
                    return invocation + ":early:" + body.read(new byte[4]);
                }
            }
            if (endpoint.endsWith("/conformance/json")) {
                Response<JSONObject> response = request.asJsonObject();
                checkMessage(response);
                JSONObject body = response.getBody();
                JSONArray items = body.getJSONArray("items");
                String json = "{\"empty\":" + JSONObject.quote(body.getString("empty"))
                    + ",\"id\":" + body.getInt("id") + ",\"items\":["
                    + JSONObject.quote(items.getString(0)) + "," + JSONObject.quote(items.getString(1))
                    + "],\"name\":" + JSONObject.quote(body.getString("name")) + "}";
                return invocation + ":" + response.getStatusCode() + ":" + json;
            }
            Response<String> response = request.asString();
            checkMessage(response);
            if (response.getStatusCode() / 100 == 3) response.ensureSuccess();
            Object body = response.isSuccess() ? response.getBody() : response.getErrorBody();
            return invocation + ":" + response.getStatusCode() + ":" + body;
        } catch (Exception failure) {
            Throwable cause = failure;
            for (int n = 0; n < 8; n++) {
                if (cause instanceof HttpFailure typed) return invocation + ":transport:" + typed.code();
                if (cause.getCause() == null || cause.getCause() == cause) break;
                cause = cause.getCause();
            }
            return invocation + ":io-error";
        }
    }
}

package dev.latent.sdk.transport;

import com.google.gson.JsonParser;
import dev.latent.sdk.Management;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Fresh-query validation against a provisioned node and committed state. */
public final class Phase4RealQuery {
    private Phase4RealQuery() { }
    private static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) throw new IllegalArgumentException("missing fixture field: " + key);
        return value;
    }
    private static void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private static byte[] bytes(ByteBuffer value) {
        var copy = value.asReadOnlyBuffer(); byte[] out = new byte[copy.remaining()]; copy.get(out); return out;
    }
    public static void main(String[] args) throws Exception {
        String tenant = required("LSF_401_TENANT"); byte[] minimum = HexFormat.of().parseHex(required("LSF_401_QUERY_MINIMUM_HEX"));
        check(minimum.length > 0, "minimum view");
        var namespace = new Transactions.NamespaceSelector(tenant, required("LSF_401_NAMESPACE"), required("LSF_401_INCARNATION"));
        var options = new Management.CallOptions(Optional.of(15000L));
        var client = new RpcClient(ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_TOKEN")));
        try {
            for (int i = 0; i < 3; ++i) {
                var target = new Management.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "query", Optional.of("transaction-java-aggregate"));
                var budget = new Management.ResourceBudget(1000000000L, 67108864L, 0, 0, 4194304L, 0, 0, 0, 0, 0, Optional.of(120000L));
                var invoke = new Management.InvokeRequest(Optional.of("java-sdk-fresh-query-" + i), Optional.empty(), Optional.empty(), Optional.of(target), ByteBuffer.wrap("[]".getBytes(StandardCharsets.UTF_8)), "application/vnd.latent.wit-values.v1+json", Optional.empty(), 0, Optional.empty(), Optional.of(budget), Map.of());
                var request = new Transactions.QueryRequest(Optional.of(Transactions.currentProfile()), Optional.of(invoke), Optional.of(namespace), Optional.empty(), Optional.of(ByteBuffer.wrap(minimum)));
                var value = client.query(request, options).get(20, TimeUnit.SECONDS).value();
                var view = value.view().orElseThrow(); var success = value.invocation().orElseThrow().success().orElseThrow();
                check(view.namespace().orElseThrow().equals(namespace) && java.util.Arrays.equals(bytes(view.version()), minimum), "scope and view");
                check(value.source().isPresent() && success.committedStateVersion().isEmpty() && success.effectIds().isEmpty(), "query-only outcome");
                var frame = JsonParser.parseString(new String(bytes(success.payload()), StandardCharsets.UTF_8)).getAsJsonArray();
                check(frame.size() == 1, "result frame"); var result = frame.get(0).getAsJsonObject().getAsJsonObject("ok");
                check(result.get("count").getAsString().equals("2"), "committed value"); var token = result.getAsJsonArray("view-version");
                check(token.size() == minimum.length, "result view size");
                for (int j = 0; j < minimum.length; ++j) check(token.get(j).getAsInt() == Byte.toUnsignedInt(minimum[j]), "result view identity");
            }
            System.out.println("FRESH_QUERY_AFTER_COMMIT");
        } finally { check(client.shutdown(Duration.ofSeconds(5)).clean(), "client retirement"); }
    }
}

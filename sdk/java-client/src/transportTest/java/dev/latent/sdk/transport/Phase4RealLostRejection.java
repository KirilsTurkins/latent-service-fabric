package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Explicit lost rejection and fresh-client recovery on a provisioned node. */
public final class Phase4RealLostRejection {
    private Phase4RealLostRejection() { }
    private static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) throw new IllegalArgumentException("missing fixture field: " + key);
        return value;
    }
    private static void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    private static String hex(ByteBuffer value) {
        ByteBuffer copy = value.asReadOnlyBuffer(); byte[] bytes = new byte[copy.remaining()]; copy.get(bytes);
        return HexFormat.of().formatHex(bytes);
    }
    public static void main(String[] args) throws Exception {
        String tenant = required("LSF_401_TENANT"), key = "java-sdk-lost-rejection";
        var namespace = new Transactions.NamespaceSelector(tenant, required("LSF_401_NAMESPACE"), required("LSF_401_INCARNATION"));
        var selector = new Transactions.CommandSelector(Optional.of(namespace), "update", Optional.empty(), key, Optional.empty());
        var options = new Management.CallOptions(Optional.of(5000L));
        var config = ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_TOKEN"));
        var client = new RpcClient(config);
        try {
            String mode = required("LSF_401_MODE");
            if (mode.equals("recover")) {
                var lookup = new Transactions.LookupCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(selector), Optional.empty(),
                        Optional.of(new Management.PublicationRef(required("LSF_401_PUBLICATION"), tenant)));
                var value = client.lookupCommand(lookup, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
                check(value.outcome().equals(Transactions.CommandOutcome.REJECTED) && value.metadataDurable() && !value.applicationStateCommitted() && value.commit().isEmpty(), "durable rejection");
                check(value.commandId().equals(required("LSF_401_ORIGINAL_ID")) && value.attemptId().equals(required("LSF_401_ORIGINAL_ATTEMPT")) && hex(value.fingerprintSha256()).equals(required("LSF_401_ORIGINAL_FINGERPRINT")), "original identity");
                var rejection=value.businessRejection().orElseThrow(); check(HexFormat.of().formatHex(rejection.code().getBytes(StandardCharsets.UTF_8)).equals(required("LSF_401_REJECTION_CODE")) && hex(rejection.payload()).equals(required("LSF_401_REJECTION_PAYLOAD")), "original rejection");
                System.out.println("LOST_REJECTION_RECOVERED");
            } else {
                check(mode.equals("invoke") || mode.equals("conflict"), "mode");
                byte[] version = HexFormat.of().parseHex(required("LSF_401_EXPECTED_VERSION_HEX")); check(version.length > 0, "current key version");
                var target = new Management.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", Optional.of("transaction-java-aggregate"));
                var budget = new Management.ResourceBudget(1_000_000_000L, 67_108_864L, 0, 0, 4_194_304L, 2_097_152L, 0, 0, 0, 1, Optional.of(120_000L));
                var invocation = new Management.InvokeRequest(Optional.of(key), Optional.empty(), Optional.empty(), Optional.of(target),
                        ByteBuffer.wrap((mode.equals("conflict") ? "[{\"delta\":2,\"reject\":true}]" : "[{\"delta\":1,\"reject\":true}]").getBytes(StandardCharsets.UTF_8)), "application/vnd.latent.wit-values.v1+json", Optional.empty(), 0, Optional.empty(), Optional.of(budget), Map.of());
                var expected = new Transactions.ExpectedVersion(ByteBuffer.wrap("aggregate/count".getBytes(StandardCharsets.UTF_8)), Optional.empty(), Optional.of(ByteBuffer.wrap(version)));
                var request = new Transactions.InvokeCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(invocation), Optional.of(selector), "lsf-wit-values-v1", List.of(expected), Optional.empty());
                boolean failed = false;
                try { client.invokeCommand(request, options).get(20, TimeUnit.SECONDS); }
                catch (Exception error) {
                    var failure=TransactionClient.clientFailure(error).orElseThrow();
                    check(failure.transport().dispatched() && failure.transport().outcome().equals(Management.OutcomeKnowledge.UNKNOWN), "dispatched unknown");
                    check(failure.identity().command().orElseThrow().clientKey().equals(key) && failure.observed().isEmpty(), "original identity without fabricated outcome");
                    if (mode.equals("conflict")) check(failure.transport().grpcStatus().orElse(-1) == 6, "retained key conflict");
                    failed = true;
                }
                check(failed, "response must be withheld");
                System.out.println(mode.equals("conflict") ? "CHANGED_INPUT_CONFLICT" : "LOST_REJECTION_UNKNOWN");
            }
        } finally { check(client.shutdown(Duration.ofSeconds(5)).clean(), "client retirement"); }
    }
}

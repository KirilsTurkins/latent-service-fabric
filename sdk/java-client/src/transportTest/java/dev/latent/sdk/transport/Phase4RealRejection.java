package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Explicit business rejection and fresh-client recovery on a provisioned node. */
public final class Phase4RealRejection {
    private Phase4RealRejection() { }
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
        String tenant = required("LSF_401_TENANT"), key = "java-sdk-rejected-command";
        var namespace = new Transactions.NamespaceSelector(tenant, required("LSF_401_NAMESPACE"), required("LSF_401_INCARNATION"));
        var selector = new Transactions.CommandSelector(Optional.of(namespace), "update", Optional.empty(), key, Optional.empty());
        var options = new Management.CallOptions(Optional.of(5000L));
        var config = ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_TOKEN"));
        var client = new RpcClient(config);
        try {
            if (required("LSF_401_MODE").equals("recover")) {
                var lookup = new Transactions.LookupCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(selector), Optional.empty(),
                        Optional.of(new Management.PublicationRef(required("LSF_401_PUBLICATION"), tenant)));
                var command = client.lookupCommand(lookup, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
                var rejection = command.businessRejection().orElseThrow();
                System.err.printf("REJECTION_FIELDS outcome=%s durable=%s committed=%s hasCommit=%s%n", command.outcome(), command.metadataDurable(), command.applicationStateCommitted(), command.commit().isPresent());
                check(command.outcome().equals(Transactions.CommandOutcome.REJECTED) && command.metadataDurable() && !command.applicationStateCommitted() && command.commit().isEmpty(), "durable rejection");
                check(command.commandId().equals(required("LSF_401_REJECTION_ID")) && command.attemptId().equals(required("LSF_401_REJECTION_ATTEMPT")) && hex(command.fingerprintSha256()).equals(required("LSF_401_REJECTION_FINGERPRINT")), "original identity");
                check(HexFormat.of().formatHex(rejection.code().getBytes(StandardCharsets.UTF_8)).equals(required("LSF_401_REJECTION_CODE")) && hex(rejection.payload()).equals(required("LSF_401_REJECTION_PAYLOAD")), "original rejection payload");
                System.out.println("REJECTION_RECOVERED");
            } else {
                check(required("LSF_401_MODE").equals("reject"), "mode");
                byte[] version = HexFormat.of().parseHex(required("LSF_401_EXPECTED_VERSION_HEX")); check(version.length > 0, "current key version");
                var target = new Management.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", Optional.of("transaction-java-aggregate"));
                var budget = new Management.ResourceBudget(1_000_000_000L, 67_108_864L, 0, 0, 4_194_304L, 2_097_152L, 0, 0, 0, 1, Optional.of(120_000L));
                var invocation = new Management.InvokeRequest(Optional.of(key), Optional.empty(), Optional.empty(), Optional.of(target),
                        ByteBuffer.wrap("[{\"delta\":1,\"reject\":true}]".getBytes(StandardCharsets.UTF_8)), "application/vnd.latent.wit-values.v1+json", Optional.empty(), 0, Optional.empty(), Optional.of(budget), Map.of());
                var expected = new Transactions.ExpectedVersion(ByteBuffer.wrap("aggregate/count".getBytes(StandardCharsets.UTF_8)), Optional.empty(), Optional.of(ByteBuffer.wrap(version)));
                var request = new Transactions.InvokeCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(invocation), Optional.of(selector), "lsf-wit-values-v1", List.of(expected), Optional.empty());
                var response = client.invokeCommand(request, options).get(10, TimeUnit.SECONDS).value();
                var command = response.command().orElseThrow(); var rejection = response.invocation().orElseThrow().declaredError().orElseThrow();
                System.err.printf("REJECTION_FIELDS outcome=%s durable=%s committed=%s hasCommit=%s%n", command.outcome(), command.metadataDurable(), command.applicationStateCommitted(), command.commit().isPresent());
                check(command.outcome().equals(Transactions.CommandOutcome.REJECTED) && command.metadataDurable() && !command.applicationStateCommitted() && command.commit().isEmpty(), "durable rejection");
                System.out.printf("REJECTION %s %s %s %s %s%n", command.commandId(), command.attemptId(), hex(command.fingerprintSha256()), HexFormat.of().formatHex(rejection.code().getBytes(StandardCharsets.UTF_8)), hex(rejection.payload()));
            }
        } finally { check(client.shutdown(Duration.ofSeconds(5)).clean(), "client retirement"); }
    }
}

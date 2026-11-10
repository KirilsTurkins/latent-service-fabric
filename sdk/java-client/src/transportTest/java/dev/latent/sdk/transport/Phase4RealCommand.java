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

/** Explicit version-fenced command against a separately provisioned node. */
public final class Phase4RealCommand {
    private Phase4RealCommand() { }
    private static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) throw new IllegalArgumentException("missing fixture field: " + key);
        return value;
    }
    private static void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    public static void main(String[] args) throws Exception {
        String tenant = required("LSF_401_TENANT"), key = "java-sdk-direct-command";
        byte[] version = HexFormat.of().parseHex(required("LSF_401_EXPECTED_VERSION_HEX"));
        check(version.length > 0, "current key version");
        var namespace = new Transactions.NamespaceSelector(tenant, required("LSF_401_NAMESPACE"), required("LSF_401_INCARNATION"));
        var selector = new Transactions.CommandSelector(Optional.of(namespace), "update", Optional.empty(), key, Optional.empty());
        var target = new Management.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", Optional.of("transaction-java-aggregate"));
        var budget = new Management.ResourceBudget(1_000_000_000L, 67_108_864L, 0, 0, 4_194_304L, 2_097_152L, 0, 0, 0, 1, Optional.of(120_000L));
        var invocation = new Management.InvokeRequest(Optional.of(key), Optional.empty(), Optional.empty(), Optional.of(target),
                ByteBuffer.wrap("[{\"delta\":1,\"reject\":false}]".getBytes(StandardCharsets.UTF_8)), "application/vnd.latent.wit-values.v1+json",
                Optional.empty(), 0, Optional.empty(), Optional.of(budget), Map.of());
        var expected = new Transactions.ExpectedVersion(ByteBuffer.wrap("aggregate/count".getBytes(StandardCharsets.UTF_8)), Optional.empty(), Optional.of(ByteBuffer.wrap(version)));
        var request = new Transactions.InvokeCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(invocation), Optional.of(selector),
                "lsf-wit-values-v1", List.of(expected), Optional.empty());
        var options = new Management.CallOptions(Optional.of(5000L));
        var config = ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_TOKEN"));
        var client = new RpcClient(config);
        try {
            try {
                var command = client.invokeCommand(request, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
                check(command.outcome().equals(Transactions.CommandOutcome.COMMITTED) && command.metadataDurable() && command.applicationStateCommitted(), "committed command");
                var commit = command.commit().orElseThrow(); check(commit.effectIds().size() == 1, "one effect");
                System.out.printf("RESULT %s %s %s%n", command.commandId(), command.attemptId(), commit.effectIds().getFirst());
            } catch (Exception failure) {
                var observed = TransactionClient.clientFailure(failure);
                if (observed.isPresent()) { var transport = observed.orElseThrow().transport(); System.err.printf("DIAGNOSTIC category=%s outcome=%s dispatched=%s%n", transport.category(), transport.outcome(), transport.dispatched()); }
                var recovery = new RpcClient(config);
                try {
                    var lookup = new Transactions.LookupCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(selector), Optional.empty(),
                            Optional.of(new Management.PublicationRef(required("LSF_401_PUBLICATION"), tenant)));
                    var original = recovery.lookupCommand(lookup, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
                    System.err.printf("RECOVERY outcome=%s durable=%s committed=%s effects=%d%n", original.outcome(), original.metadataDurable(), original.applicationStateCommitted(), original.commit().orElseThrow().effectIds().size());
                } finally { check(recovery.shutdown(Duration.ofSeconds(5)).clean(), "recovery retirement"); }
                throw failure;
            }
        } finally { check(client.shutdown(Duration.ofSeconds(5)).clean(), "client retirement"); }
    }
}

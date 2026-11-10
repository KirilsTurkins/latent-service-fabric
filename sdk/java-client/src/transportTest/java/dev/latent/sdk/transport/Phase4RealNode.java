package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.Transactions;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Explicit live-node probe; the caller provisions the committed fixture. */
public final class Phase4RealNode {
    private Phase4RealNode() { }
    private static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isEmpty()) throw new IllegalArgumentException("missing live fixture field: " + key);
        return value;
    }
    private static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    public static void main(String[] args) throws Exception {
        String tenant = required("LSF_401_TENANT"), key = required("LSF_401_COMMAND_KEY");
        var namespace = new Transactions.NamespaceSelector(tenant, required("LSF_401_NAMESPACE"), required("LSF_401_INCARNATION"));
        var selector = new Transactions.CommandSelector(Optional.of(namespace), required("LSF_401_OPERATION"), Optional.empty(), key, Optional.empty());
        var publication = new Management.PublicationRef(required("LSF_401_PUBLICATION"), tenant);
        var request = new Transactions.LookupCommandRequest(Optional.of(Transactions.currentProfile()), Optional.of(selector), Optional.empty(), Optional.of(publication));
        var client = new RpcClient(ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_TOKEN")));
        try {
            var options = new Management.CallOptions(Optional.of(5000L));
            var first = client.lookupCommand(request, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
            var second = client.lookupCommand(request, options).get(10, TimeUnit.SECONDS).value().command().orElseThrow();
            check(first.commandId().equals(required("LSF_401_COMMAND_ID")), "command identity");
            check(first.attemptId().equals(required("LSF_401_ATTEMPT_ID")), "attempt identity");
            check(first.key().orElseThrow().clientKey().equals(key), "command key");
            check(first.outcome().equals(Transactions.CommandOutcome.COMMITTED) && first.metadataDurable()
                    && first.applicationStateCommitted() && first.commit().isPresent(), "committed outcome");
            check(first.commandId().equals(second.commandId()) && first.attemptId().equals(second.attemptId())
                    && first.key().equals(second.key()) && first.fingerprintSha256().equals(second.fingerprintSha256())
                    && first.outcome().equals(second.outcome()) && first.source().equals(second.source())
                    && first.commit().equals(second.commit()), "stable original receipt");
        } finally {
            check(client.shutdown(Duration.ofSeconds(5)).clean(), "client owner retirement");
        }
        System.out.println("Java live original-command lookup and shutdown passed");
    }
}

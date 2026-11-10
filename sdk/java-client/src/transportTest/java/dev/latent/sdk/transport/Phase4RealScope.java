package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.TimeUnit;

/** Explicit caller-scope refusal on a provisioned node. */
public final class Phase4RealScope {
    private Phase4RealScope() { }
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
        var client = new RpcClient(ClientConfig.loopback("http://" + required("LSF_401_ENDPOINT"), tenant, required("LSF_401_SCOPE_TOKEN")));
        try {
            var options = new Management.CallOptions(Optional.of(5000L));
            boolean refused = false;
            try { client.lookupCommand(request, options).get(10, TimeUnit.SECONDS); }
            catch (Exception error) {
                var failure = TransactionClient.clientFailure(error).orElseThrow();
                check(failure.transport().grpcStatus().orElseThrow() == 7 && failure.observed().isEmpty(), "scope refusal");
                refused = true;
            }
            check(refused, "different caller must not recover original");
        } finally {
            check(client.shutdown(Duration.ofSeconds(5)).clean(), "client owner retirement");
        }
        System.out.println("SCOPE_REFUSED grpc=7");
    }
}

package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import java.util.Optional;

/** The original signed fixture contract, with an explicitly selected installed target. */
final class Phase4Aggregate {
    private Phase4Aggregate() { }

    static Management.InvocationTarget target(String tenant, String function) {
        var environment = System.getenv();
        String service = environment.getOrDefault("LSF_401_AGGREGATE_SERVICE", "examples/transaction-java-aggregate");
        String route = environment.getOrDefault("LSF_401_AGGREGATE_ROUTE", "transaction-java-aggregate");
        if (function.equals("query")) {
            route = environment.getOrDefault("LSF_401_AGGREGATE_QUERY_ROUTE", route);
        }
        return new Management.InvocationTarget(tenant, service, "examples:transactional-aggregate/api@1.0.0",
                function, Optional.of(route));
    }
}

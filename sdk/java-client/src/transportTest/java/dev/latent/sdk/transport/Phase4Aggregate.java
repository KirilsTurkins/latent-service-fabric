package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import java.util.Optional;

/** The original signed fixture contract, with an explicitly selected installed target. */
final class Phase4Aggregate {
    private Phase4Aggregate() { }

    static long wallTimeLimitMillis() {
        String value = System.getenv("LSF_401_WALL_TIME_MILLIS");
        if (value == null) return 120_000L;
        long millis = Long.parseLong(value);
        if (millis <= 0 || millis > 120_000L || !Long.toString(millis).equals(value)) {
            throw new IllegalArgumentException("invalid fixture wall-time limit");
        }
        return millis;
    }

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

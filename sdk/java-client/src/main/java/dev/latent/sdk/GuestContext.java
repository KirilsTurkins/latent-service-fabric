package dev.latent.sdk;

import java.util.Map;
import java.util.Optional;

public interface GuestContext {
    String activationId();

    String rootActivationId();

    Optional<String> parentActivationId();

    Optional<Long> deadlineUnixMillis();

    Models.ResourceBudget remainingBudget();

    Map<String, String> metadata();
}

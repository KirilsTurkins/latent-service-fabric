package dev.latent.sdk;

import java.util.concurrent.CompletionStage;

public interface LatentClient {
    CompletionStage<Models.InvocationOutcome> invoke(Models.InvokeRequest request);

    CompletionStage<Models.CancelResponse> cancel(String activationId, String reason);

    CompletionStage<Models.ActivationStatus> getActivation(String activationId);
}

package dev.latent.sdk;

import java.util.concurrent.CompletionStage;

public interface LatentClient {
    CompletionStage<InvokeResponse> invoke(InvokeRequest request);

    CompletionStage<Void> cancel(String activationId, String reason);
}

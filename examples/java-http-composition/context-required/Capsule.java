package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentContextContext;

/** An ordinary capsule importing context requires an explicit trusted binding. */
public final class Capsule implements Bindings.Exports {
    public String status() {
        return LatentContextContext.principal().kind();
    }
}

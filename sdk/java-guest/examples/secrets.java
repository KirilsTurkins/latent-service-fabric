package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var result = LatentSecretsReader.read(text);
        if (!result.isError()) {
            try (var owned = new SensitiveBytes(result.value().bytes())) { return new Unsigned64(owned.borrow().length); }
        }
        return new Unsigned64(switch (result.error().tag()) {
            case 1 -> 10; case 0 -> 11; case 2 -> 12; case 3 -> 13;
            default -> throw new IllegalStateException("unexpected secret error");
        });
    }
}

package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;

public final class Capsule implements Bindings.Exports {
    private static Unsigned64 inspectOwned(byte[] value) {
        try (var owned = new SensitiveBytes(value)) {
            SensitiveBytes alias = owned;
            byte[] retained = alias.borrow();
            if (retained != value) throw new IllegalStateException("secret owner did not adopt bytes");
            int length = retained.length;
            owned.close();
            alias.close(); // Idempotent through the same owner, not a second release.
            for (byte part : retained) {
                if (part != 0) throw new IllegalStateException("retained secret alias was not cleared");
            }
            boolean rejected = false;
            try { alias.borrow(); }
            catch (IllegalStateException expected) { rejected = true; }
            if (!rejected) throw new IllegalStateException("closed secret owner remained readable");
            return new Unsigned64(length);
        }
    }
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var result = LatentSecretsReader.read(text);
        if (!result.isError()) return inspectOwned(result.value().bytes());
        return new Unsigned64(switch (result.error().tag()) {
            case 1 -> 10; case 0 -> 11; case 2 -> 12; case 3 -> 13;
            default -> throw new IllegalStateException("unexpected secret error");
        });
    }
}

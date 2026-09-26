package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.util.Arrays;

public final class Capsule implements Bindings.Exports {
    private static final Unsigned64 ZERO = new Unsigned64(0);
    private static void close(Unsigned64 value) { LatentBlobBlob.close(value).value(); }
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        if (which == 2 || which == 4) {
            Unsigned64 value = handle;
            if (which == 2) {
                value = LatentBlobBlob.create("text/plain", Option.some(ZERO)).value();
                if (!LatentBlobBlob.close(value).value()) throw new IllegalStateException("not closed");
            }
            var rejected = LatentBlobBlob.write(value, ZERO, new byte[0]);
            if (!rejected.isError()) throw new IllegalStateException("closed or foreign handle accepted");
            return new Unsigned64(switch (rejected.error().tag()) {
                case 3 -> 10; case 1 -> 11; default -> throw new IllegalStateException("unexpected blob rejection");
            });
        }
        // Intentionally abandoned owner tests Store-level activation cleanup.
        if (which == 5) return LatentBlobBlob.create("text/plain", Option.some(ZERO)).value();
        try (var writer = new Handle(LatentBlobBlob.create("text/plain", Option.some(new Unsigned64(4))).value(), Capsule::close)) {
            if (which == 1) return new Unsigned64(1);
            byte[] data = {100, 97, 116, 97};
            if (LatentBlobBlob.write(writer.borrow(), ZERO, data).value().bits() != 4) throw new IllegalStateException("short write");
            var reference = LatentBlobBlob.seal(writer.consume()).value();
            try (var reader = new Handle(LatentBlobBlob.open(reference).value(), Capsule::close);
                 var chunk = LatentBlobBlob.read(reader.borrow(), ZERO, 4L).value()) {
                reader.close();
                if (which == 3) return new Unsigned64(3);
                byte[] actual = LatentBlobBlob.chunkBytes(chunk).value();
                if (!Arrays.equals(actual, data)) throw new IllegalStateException("blob contents mismatch");
                return new Unsigned64(actual.length);
            }
        }
    }
}

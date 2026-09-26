package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import dev.latent.guest.Text;

// lsf-example-begin: capsule
public final class Capsule implements Bindings.Exports {
    public Result<String, String> greet(String name) {
        String trimmed = Text.trim(name);
        if (trimmed.isEmpty()) return Result.err("Please enter a name.");
        if (Text.utf8Length(trimmed) > 100) return Result.err("Use a name of at most 100 bytes.");
        return Result.ok("Hello, " + trimmed + "!");
    }
}
// lsf-example-end: capsule

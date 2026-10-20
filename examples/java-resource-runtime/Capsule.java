package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import dev.latent.guest.Text;
import outside.resourceruntime.Library;

public final class Capsule implements Bindings.Exports {
    public Result<String, String> greet(String name) {
        if (name.startsWith("resource-runtime:")) {
            return Result.ok(Library.run(name.substring("resource-runtime:".length())));
        }
        String trimmed = Text.trim(name);
        if (trimmed.isEmpty()) return Result.err("Please enter a name.");
        if (Text.utf8Length(trimmed) > 100) return Result.err("Use a name of at most 100 bytes.");
        return Result.ok("Hello, " + trimmed + "!");
    }
}

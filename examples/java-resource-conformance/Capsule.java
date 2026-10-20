package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import dev.latent.guest.Text;
import outside.resources.Library;

public final class Capsule implements Bindings.Exports {
    private static int visits;

    public Result<String, String> greet(String name) {
        if (name.startsWith("resources:")) {
            String mode = name.substring("resources:".length());
            if (++visits != 1) throw new IllegalStateException("resource-state-survived");
            if (mode.equals("trap")) throw new IllegalStateException("resource-fixture-trap");
            if (mode.equals("clock")) {
                long first = System.nanoTime();
                long wall = System.currentTimeMillis();
                long second = System.nanoTime();
                return Result.ok("clock|wall=" + wall + "|first=" + first + "|second=" + second + "|fresh=1");
            }
            return Result.ok(Library.read(mode) + "|fresh=1");
        }
        String trimmed = Text.trim(name);
        if (trimmed.isEmpty()) return Result.err("Please enter a name.");
        if (Text.utf8Length(trimmed) > 100) return Result.err("Use a name of at most 100 bytes.");
        return Result.ok("Hello, " + trimmed + "!");
    }
}

package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import outside.diagnostics.Library;

public final class Capsule implements Bindings.Exports {
    private static void selectedCompilerEdge() { }
    public Result<String, String> greet(String name) {
        selectedCompilerEdge();
        return Result.ok(new Library().run(name));
    }
}

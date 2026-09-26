package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Result;

public final class Capsule implements Bindings.Exports {
    private static volatile long counter;
    public Long answer() { return 42L; }
    public Result<Long, String> fail() { return Result.err("declared application failure"); }
    public Long spin() { for (;;) counter++; }
}

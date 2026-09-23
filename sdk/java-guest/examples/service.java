package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var target = new LatentServiceInvokeTarget(Option.none(), "callee", "tests:local/api@1.0.0",
            which == 0 ? "answer" : which == 1 ? "fail" : "spin", Option.some("callee"));
        var result = LatentServiceInvoke.call(target, "[]".getBytes(StandardCharsets.UTF_8),
            "application/vnd.latent.wit-values.v1+json", new LatentServiceInvokeCallOptions(Option.none(), (short) 0, Option.none(), List.of()));
        if (result.tag() == 0) {
            if (!Arrays.equals(result.successValue().payload(), "[42]".getBytes(StandardCharsets.UTF_8))) throw new IllegalStateException("callee payload mismatch");
            return new Unsigned64(42);
        }
        if (result.tag() == 1) {
            if (result.declaredErrorValue().payload().length == 0) throw new IllegalStateException("missing declared error");
            return new Unsigned64(10);
        }
        return new Unsigned64(switch (result.platformFailureValue().code()) {
            case PermissionDenied -> 11; case Cancelled -> 12; case DeadlineExceeded -> 13; case ResourceExhausted -> 14;
            default -> throw new IllegalStateException("unexpected service platform failure");
        });
    }
}

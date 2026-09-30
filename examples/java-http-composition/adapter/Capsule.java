package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.Option;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;

/** Explicit public operations; the typed domain keeps its wider private API. */
public final class Capsule implements Bindings.Exports {
    public LatentWebApplicationResponse handle(LatentWebApplicationRequest request) {
        String operation = switch (request.path()) {
            case "/api/status" -> request.method() == LatentWebApplicationMethod.Get ? "status" : null;
            case "/api/echo" -> request.method() == LatentWebApplicationMethod.Post ? "echo" : null;
            case "/api/text" -> request.method() == LatentWebApplicationMethod.Post ? "text" : null;
            case "/api/items" -> request.method() == LatentWebApplicationMethod.Post ? "items" : null;
            case "/api/fail" -> request.method() == LatentWebApplicationMethod.Get ? "fail" : null;
            case "/api/throw" -> request.method() == LatentWebApplicationMethod.Get ? "throw-error" : null;
            case "/api/spin" -> request.method() == LatentWebApplicationMethod.Get ? "spin" : null;
            default -> null;
        };
        if (operation == null) return response(404, "route-not-selected".getBytes(StandardCharsets.UTF_8));
        byte[] input;
        try {
            input = request.method() == LatentWebApplicationMethod.Get ? "[]".getBytes(StandardCharsets.UTF_8)
                : Base64.getDecoder().decode(request.bodyBase64());
        } catch (IllegalArgumentException invalid) {
            return response(400, "malformed-body".getBytes(StandardCharsets.UTF_8));
        }
        var target = new LatentServiceInvokeTarget(Option.none(), "examples/java-http-domain",
            "examples:java-http-domain/api@1.0.0", operation, Option.some("java-http-domain"));
        var result = LatentServiceInvoke.call(target, input,
            "application/vnd.latent.wit-values.v1+json",
            new LatentServiceInvokeCallOptions(Option.none(), (short) 0, Option.none(), List.of()));
        if (result.tag() == 0) return response(200, result.successValue().payload());
        if (result.tag() == 1) return response(422, result.declaredErrorValue().payload());
        return response(switch (result.platformFailureValue().code()) {
            case PermissionDenied, Unauthenticated -> 403;
            case InvalidArgument -> 400;
            case DeadlineExceeded -> 504;
            case ResourceExhausted, Unavailable, Cancelled -> 503;
            default -> 500;
        }, "child-platform-failure".getBytes(StandardCharsets.UTF_8));
    }
    private static LatentWebApplicationResponse response(int status, byte[] body) {
        return new LatentWebApplicationResponse(LatentWebApplicationProfile.BufferedV1, status,
            List.of(), Option.some("application/json"), Option.none(), Base64.getEncoder().encodeToString(body));
    }
}

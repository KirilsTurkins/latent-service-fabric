package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import dev.latent.guest.server.http.Headers;
import dev.latent.guest.server.http.HttpExchange;
import dev.latent.guest.server.http.ServerSession;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Locale;

/** Compiler-generated invocation bridge; applications keep ordinary server source. */
public final class Capsule implements Bindings.Exports {
    public LatentWebApplicationResponse handle(LatentWebApplicationRequest request) {
        // Retain the authoritative context interface; request headers never supply it.
        Bindings.LatentContextContext.activationId();
        Headers fields = new Headers();
        for (var header : request.headers()) {
            fields.add(header.name(), new String(header.value(), StandardCharsets.ISO_8859_1));
        }
        if (request.mediaType().isSome()) fields.set("content-type", request.mediaType().value());
        HttpExchange exchange = new HttpExchange(request.method().name().toUpperCase(Locale.ROOT), request.path(),
            request.query().isSome() ? request.query().value() : null, fields,
            Base64.getDecoder().decode(request.bodyBase64()));
        ServerSession.begin();
        try {
            /*LSF_INITIALIZER*/.main(new String[0]);
            ServerSession.verify(/*LSF_DECLARED_REGISTRATION*/);
            ServerSession.dispatch(exchange);
            byte[] body = exchange.sealedBody();
            var headers = new ArrayList<LatentWebApplicationHeader>();
            for (var header : exchange.sealedHeaders().entrySet()) {
                if (header.getKey().equals("content-type")) continue;
                for (String value : header.getValue()) {
                    headers.add(new LatentWebApplicationHeader(header.getKey(), value.getBytes(StandardCharsets.ISO_8859_1)));
                }
            }
            return new LatentWebApplicationResponse(LatentWebApplicationProfile.BufferedV1, exchange.getResponseCode(), headers,
                exchange.mediaType() == null ? Option.none() : Option.some(exchange.mediaType()),
                exchange.representationLength() == null ? Option.none() : Option.some(new Unsigned64(exchange.representationLength())),
                Base64.getEncoder().encodeToString(body));
        } catch (Exception failure) {
            throw new IllegalStateException("server activation failed", failure);
        } finally {
            exchange.retire();
            ServerSession.retire();
        }
    }
}

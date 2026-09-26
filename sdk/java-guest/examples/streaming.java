package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var opened = LatentHttpStreaming.open(new LatentHttpStreamingRequest(LatentHttpStreamingMethod.Post,
            text, List.of(), Option.some(new Unsigned64(4)), Option.some("text/plain"), Option.none(), Option.some(new Unsigned64(1000))));
        if (opened.isError()) {
            if (opened.error().tag() == 2) return new Unsigned64(10);
            throw new IllegalStateException("unexpected HTTP open error");
        }
        try (var upload = opened.value()) {
            if (which == 1) return new Unsigned64(1);
            LatentHttpStreaming.write(upload, new byte[]{100, 97, 116, 97}).value();
            var response = LatentHttpStreaming.finish(upload).value(); // consumes upload on any outcome
            try (var body = response.body()) {
                if (which == 2) return new Unsigned64(2);
                long count = 0;
                for (;;) {
                    var next = LatentHttpStreaming.read(body, 4L).value();
                    if (!next.isSome()) break;
                    try (var chunk = next.value()) {
                        if (which == 3) body.close(); // chunk remains an independent charged owner
                        count += LatentHttpStreaming.chunkBytes(chunk).value().length;
                        if (which == 3) return new Unsigned64(count);
                    }
                }
                LatentHttpStreaming.trailers(body).value();
                var again = LatentHttpStreaming.trailers(body);
                if (!again.isError() || again.error().tag() != 13) throw new IllegalStateException("trailers accepted twice");
                return new Unsigned64(count);
            }
        }
    }
}

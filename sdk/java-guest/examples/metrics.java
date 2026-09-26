package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        var kind = which == 0 ? LatentTelemetryCustomMetricKind.Counter : which == 1 ? LatentTelemetryCustomMetricKind.UpDownCounter
            : which == 2 ? LatentTelemetryCustomMetricKind.Gauge : LatentTelemetryCustomMetricKind.Histogram;
        var result = LatentTelemetryCustom.emitMetric(new LatentTelemetryCustomMetric(text, kind, 2.0, "1", List.of(new Value1("region", "east"))));
        if (!result.isError()) return new Unsigned64(result.value() ? 1 : 0);
        return new Unsigned64(switch (result.error().tag()) {
            case 0 -> 10; case 1 -> 11; case 2 -> 12; default -> throw new IllegalStateException("unexpected metric error");
        });
    }
}

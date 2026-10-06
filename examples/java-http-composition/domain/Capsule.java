package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.ExamplesJavaHttpDomainTypesWide;
import dev.latent.generated.Bindings.ExamplesJavaHttpDomainTypesNested;
import dev.latent.guest.Result;
import dev.latent.guest.Unsigned64;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public List<ExamplesJavaHttpDomainTypesWide> status() {
        Bindings.LatentClockMonotonic.nowNanos();
        var maximum = Unsigned64.parse("18446744073709551615");
        if (!maximum.toString().equals("18446744073709551615")
                || maximum.compareTo(Unsigned64.of(Long.MAX_VALUE)) <= 0)
            throw new IllegalStateException("unsigned-helper-range");
        return List.of(new ExamplesJavaHttpDomainTypesWide(
            "Grüße 😀", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l",
            maximum));
    }
    public ExamplesJavaHttpDomainTypesWide echo(ExamplesJavaHttpDomainTypesWide value) { return value; }
    public ExamplesJavaHttpDomainTypesNested echoNested(ExamplesJavaHttpDomainTypesNested value) { return value; }
    public String text(String value) { return value; }
    public List<String> items(List<String> value) { return value; }
    public Result<String, String> fail() { return Result.err("declared-domain-error"); }
    public String throwError() { throw new IllegalStateException("synthetic-java-exception"); }
    public Long spin() { long value = 0; while (true) value = (value + 1) & 0xffffffffL; }
    public String privateAdmin() { return "private-administration"; }
    public String publishing() { return "private-publishing"; }
    public String providerEvent() { return "private-provider-event"; }
}

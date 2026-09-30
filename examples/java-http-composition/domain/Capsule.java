package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.ExamplesJavaHttpDomainApiWide;
import dev.latent.guest.Result;
import dev.latent.guest.Unsigned64;
import java.util.List;

public final class Capsule implements Bindings.Exports {
    public List<ExamplesJavaHttpDomainApiWide> status() {
        return List.of(new ExamplesJavaHttpDomainApiWide(
            "Grüße 😀", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l",
            Unsigned64.parse("18446744073709551615")));
    }
    public ExamplesJavaHttpDomainApiWide echo(ExamplesJavaHttpDomainApiWide value) { return value; }
    public String text(String value) { return value; }
    public List<String> items(List<String> value) { return value; }
    public Result<String, String> fail() { return Result.err("declared-domain-error"); }
    public String throwError() { throw new IllegalStateException("synthetic-java-exception"); }
    public Long spin() { long value = 0; while (true) value = (value + 1) & 0xffffffffL; }
    public String privateAdmin() { return "private-administration"; }
}

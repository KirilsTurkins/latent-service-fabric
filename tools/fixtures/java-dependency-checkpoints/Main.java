// Reference JDK only; never packaged into the component.
import dev.latent.app.Capsule;

public final class Main {
    public static void main(String[] arguments) {
        var result = new Capsule().greet(arguments[0]);
        if (result.isError()) throw new AssertionError("unexpected-declared-error");
        System.out.println(result.value());
    }
}

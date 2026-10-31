// Reference JDK only; never packaged into the component.
import dev.latent.app.Capsule;
import java.lang.management.ManagementFactory;
import java.util.Set;
import java.util.stream.Collectors;

public final class Main {
    private static long collections() {
        return ManagementFactory.getGarbageCollectorMXBeans().stream()
            .mapToLong(bean -> bean.getCollectionCount()).sum();
    }

    public static void main(String[] arguments) {
        var names = ManagementFactory.getGarbageCollectorMXBeans().stream()
            .map(bean -> bean.getName()).collect(Collectors.toSet());
        if (!names.equals(Set.of("Copy", "MarkSweepCompact")))
            throw new AssertionError("reference-selected-serial-collector-required");
        long before = collections();
        var result = new Capsule().greet(arguments[0]);
        long after = collections();
        if (result.isError()) throw new AssertionError("unexpected-declared-error");
        if (arguments[0].equals("gc") && after - before < 2)
            throw new AssertionError("reference-actual-two-collections-required");
        System.out.println(result.value());
    }
}

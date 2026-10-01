import java.time.Duration;
import java.time.temporal.ChronoUnit;
import java.util.concurrent.TimeUnit;

public final class TimeUnitNativeControl {
    static long checks;
    static void require(boolean value) { checks++; if (!value) throw new AssertionError("timeunit-observable"); }
    public static void main(String[] args) {
        long[] values = {Long.MIN_VALUE, Long.MIN_VALUE + 1, -86_400_000_000_001L, -1_000_000_001L,
            -999_999L, -1, 0, 1, 999_999L, 1_000_000_001L, 86_400_000_000_001L, Long.MAX_VALUE - 1, Long.MAX_VALUE};
        for (TimeUnit unit : TimeUnit.values()) {
            var sdk = dev.latent.guest.runtime.concurrent.TimeUnit.valueOf(unit.name());
            require(sdk.toChronoUnit() == unit.toChronoUnit());
            require(dev.latent.guest.runtime.concurrent.TimeUnit.of(unit.toChronoUnit()) == unit);
            for (TimeUnit source : TimeUnit.values()) for (long value : values) {
                require(sdk.convert(value, source) == unit.convert(value, source));
            }
            for (long value : values) {
                require(sdk.toNanos(value) == unit.toNanos(value));
                require(sdk.toMicros(value) == unit.toMicros(value));
                require(sdk.toMillis(value) == unit.toMillis(value));
                require(sdk.toSeconds(value) == unit.toSeconds(value));
                require(sdk.toMinutes(value) == unit.toMinutes(value));
                require(sdk.toHours(value) == unit.toHours(value));
                require(sdk.toDays(value) == unit.toDays(value));
            }
            for (long seconds : values) for (int nanos : new int[]{0, 1, 500_000_000, 999_999_999}) {
                Duration duration = Duration.ofSeconds(seconds, nanos);
                require(sdk.convert(duration) == unit.convert(duration));
            }
        }
        for (ChronoUnit unit : ChronoUnit.values()) {
            if (unit.ordinal() <= ChronoUnit.DAYS.ordinal()) continue;
            try { dev.latent.guest.runtime.concurrent.TimeUnit.of(unit); throw new AssertionError("invalid-chrono-unit"); }
            catch (IllegalArgumentException expected) { checks++; }
        }
        try { dev.latent.guest.runtime.concurrent.TimeUnit.of(null); throw new AssertionError("null-chrono-unit"); }
        catch (NullPointerException expected) { checks++; }
        System.out.println("TIMEUNIT_NATIVE_SOURCE_CONTROL PASS checks=" + checks);
    }
}

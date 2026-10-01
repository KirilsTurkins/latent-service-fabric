package dev.latent.guest.runtime.concurrent;

/** Saturating standard conversions; finite waits preserve submillisecond parts. */
public enum TimeUnit {
    NANOSECONDS(1), MICROSECONDS(1000), MILLISECONDS(1_000_000),
    SECONDS(1_000_000_000), MINUTES(60_000_000_000L),
    HOURS(3_600_000_000_000L), DAYS(86_400_000_000_000L);
    private final long nanoseconds;
    TimeUnit(long nanoseconds) { this.nanoseconds = nanoseconds; }
    public long convert(long value, java.util.concurrent.TimeUnit source) {
        return convertScale(value, valueOf(source.name()).nanoseconds, nanoseconds);
    }
    public long convert(java.time.Duration duration) {
        long seconds = duration.getSeconds();
        long fraction = duration.getNano();
        // Duration normalizes a negative fraction into the preceding second;
        // conversions truncate toward zero and saturate the final whole value.
        if (seconds < 0 && fraction > 0) { seconds++; fraction -= 1_000_000_000; }
        long whole = convertScale(seconds, 1_000_000_000, nanoseconds);
        long part = convertScale(fraction, 1, nanoseconds);
        if (part > 0 && whole > Long.MAX_VALUE - part) return Long.MAX_VALUE;
        if (part < 0 && whole < Long.MIN_VALUE - part) return Long.MIN_VALUE;
        return whole + part;
    }
    public java.time.temporal.ChronoUnit toChronoUnit() {
        return switch (this) {
            case NANOSECONDS -> java.time.temporal.ChronoUnit.NANOS;
            case MICROSECONDS -> java.time.temporal.ChronoUnit.MICROS;
            case MILLISECONDS -> java.time.temporal.ChronoUnit.MILLIS;
            case SECONDS -> java.time.temporal.ChronoUnit.SECONDS;
            case MINUTES -> java.time.temporal.ChronoUnit.MINUTES;
            case HOURS -> java.time.temporal.ChronoUnit.HOURS;
            case DAYS -> java.time.temporal.ChronoUnit.DAYS;
        };
    }
    public static java.util.concurrent.TimeUnit of(java.time.temporal.ChronoUnit unit) {
        java.util.Objects.requireNonNull(unit);
        return switch (unit) {
            case NANOS -> java.util.concurrent.TimeUnit.NANOSECONDS;
            case MICROS -> java.util.concurrent.TimeUnit.MICROSECONDS;
            case MILLIS -> java.util.concurrent.TimeUnit.MILLISECONDS;
            case SECONDS -> java.util.concurrent.TimeUnit.SECONDS;
            case MINUTES -> java.util.concurrent.TimeUnit.MINUTES;
            case HOURS -> java.util.concurrent.TimeUnit.HOURS;
            case DAYS -> java.util.concurrent.TimeUnit.DAYS;
            default -> throw new IllegalArgumentException("unsupported-time-unit");
        };
    }
    private static long convertScale(long value, long source, long target) {
        if (source < target) return value / (target / source);
        long multiplier = source / target;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        if (value < Long.MIN_VALUE / multiplier) return Long.MIN_VALUE;
        return value * multiplier;
    }
    public long toNanos(long value) { return convertScale(value, nanoseconds, 1); }
    public long toMicros(long value) { return convertScale(value, nanoseconds, 1000); }
    public long toMillis(long value) { return convertScale(value, nanoseconds, 1_000_000); }
    public long toSeconds(long value) { return convertScale(value, nanoseconds, 1_000_000_000); }
    public long toMinutes(long value) { return convertScale(value, nanoseconds, 60_000_000_000L); }
    public long toHours(long value) { return convertScale(value, nanoseconds, 3_600_000_000_000L); }
    public long toDays(long value) { return convertScale(value, nanoseconds, 86_400_000_000_000L); }
    private int excessNanos(long timeout, long millis) {
        if (this == NANOSECONDS) return (int)(timeout - millis * 1_000_000);
        if (this == MICROSECONDS) return (int)((timeout - millis * 1000) * 1000);
        return 0;
    }
    public void timedWait(Object object, long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long millis = toMillis(timeout);
        object.wait(millis, excessNanos(timeout, millis));
    }
    public void timedJoin(Thread thread, long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long millis = toMillis(timeout);
        thread.join(millis, excessNanos(timeout, millis));
    }
    public void sleep(long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long millis = toMillis(timeout);
        Thread.sleep(millis, excessNanos(timeout, millis));
    }
}

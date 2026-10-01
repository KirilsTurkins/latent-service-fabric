package dev.latent.guest.runtime.concurrent;

/** Saturating standard conversions; finite waits preserve submillisecond parts. */
public enum TimeUnit {
    NANOSECONDS(1), MICROSECONDS(1000), MILLISECONDS(1_000_000),
    SECONDS(1_000_000_000), MINUTES(60_000_000_000L),
    HOURS(3_600_000_000_000L), DAYS(86_400_000_000_000L);
    private final long nanos;
    TimeUnit(long nanos) { this.nanos = nanos; }
    public long convert(long value, java.util.concurrent.TimeUnit source) {
        return convertScale(value, valueOf(source.name()).nanos, nanos);
    }
    private static long convertScale(long value, long source, long target) {
        if (source < target) return value / (target / source);
        long multiplier = source / target;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        if (value < Long.MIN_VALUE / multiplier) return Long.MIN_VALUE;
        return value * multiplier;
    }
    public long toNanos(long value) { return convertScale(value, nanos, 1); }
    public long toMicros(long value) { return convertScale(value, nanos, 1000); }
    public long toMillis(long value) { return convertScale(value, nanos, 1_000_000); }
    public long toSeconds(long value) { return convertScale(value, nanos, 1_000_000_000); }
    public long toMinutes(long value) { return convertScale(value, nanos, 60_000_000_000L); }
    public long toHours(long value) { return convertScale(value, nanos, 3_600_000_000_000L); }
    public long toDays(long value) { return convertScale(value, nanos, 86_400_000_000_000L); }
    public void timedWait(Object object, long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long value = toNanos(timeout);
        object.wait(value / 1_000_000, (int)(value % 1_000_000));
    }
    public void timedJoin(Thread thread, long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long value = toNanos(timeout);
        thread.join(value / 1_000_000, (int)(value % 1_000_000));
    }
    public void sleep(long timeout) throws InterruptedException {
        if (timeout <= 0) return;
        long value = toNanos(timeout);
        Thread.sleep(value / 1_000_000, (int)(value % 1_000_000));
    }
}

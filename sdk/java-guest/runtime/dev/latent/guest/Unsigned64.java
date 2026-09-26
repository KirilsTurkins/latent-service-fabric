package dev.latent.guest;

/** All 64 bits are retained. Never narrow a WIT u64 through a Java double. */
public record Unsigned64(long bits) implements Comparable<Unsigned64> {
    public static final Unsigned64 ZERO = new Unsigned64(0);
    public static Unsigned64 of(long nonnegative) {
        if (nonnegative < 0) throw new IllegalArgumentException("negative unsigned value");
        return new Unsigned64(nonnegative);
    }
    public static Unsigned64 parse(String value) { return new Unsigned64(Long.parseUnsignedLong(value)); }
    @Override public String toString() { return Long.toUnsignedString(bits); }
    @Override public int compareTo(Unsigned64 value) { return Long.compareUnsigned(bits, value.bits); }
}

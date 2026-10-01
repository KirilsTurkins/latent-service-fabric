package dev.latent.guest;

/** All 64 bits are retained. Never narrow a WIT u64 through a Java double. */
public record Unsigned64(long bits) implements Comparable<Unsigned64> {
    public static final Unsigned64 ZERO = new Unsigned64(0);
    public static Unsigned64 of(long nonnegative) {
        if (nonnegative < 0) throw new IllegalArgumentException("negative unsigned value");
        return new Unsigned64(nonnegative);
    }
    public static Unsigned64 parse(String value) {
        if (value == null || value.isEmpty()) throw new NumberFormatException("empty unsigned value");
        int start = value.charAt(0) == '+' ? 1 : 0;
        if (start == value.length()) throw new NumberFormatException("empty unsigned value");
        long parsed = 0;
        for (int index = start; index < value.length(); index++) {
            int digit = value.charAt(index) - '0';
            // floor(u64::MAX / 10) fits in a positive signed long. Check before
            // multiplication; only the final valid result may set its top bit.
            if (digit < 0 || digit > 9 || parsed < 0 || parsed > 1844674407370955161L
                    || parsed == 1844674407370955161L && digit > 5)
                throw new NumberFormatException("invalid or overflowing unsigned value");
            parsed = parsed * 10 + digit;
        }
        return new Unsigned64(parsed);
    }
    @Override public String toString() {
        char[] digits = new char[20];
        int position = digits.length;
        long value = bits;
        do {
            // Unsigned division by ten without unavailable TeaVM Long helpers.
            long quotient = ((value >>> 1) / 10) << 1;
            int remainder = (int) (value - quotient * 10);
            if (remainder >= 10) { quotient++; remainder -= 10; }
            digits[--position] = (char) ('0' + remainder);
            value = quotient;
        } while (value != 0);
        return new String(digits, position, digits.length - position);
    }
    @Override public int compareTo(Unsigned64 value) {
        long left = bits ^ Long.MIN_VALUE, right = value.bits ^ Long.MIN_VALUE;
        return left < right ? -1 : left == right ? 0 : 1;
    }
}

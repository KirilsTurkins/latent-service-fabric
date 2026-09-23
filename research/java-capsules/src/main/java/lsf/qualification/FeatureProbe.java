package lsf.qualification;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Compiler corpus, not generated WIT bindings or a deployable capsule. */
public final class FeatureProbe {
    private FeatureProbe() {}

    public record Parcel(String destination, long grams) {}
    public record Quote(boolean ok, long cents, String error) {}

    public static String greet(String name) {
        if (name.isEmpty()) {
            throw new IllegalArgumentException("empty name");
        }
        return "Hello, " + name + "!";
    }

    // A deliberately explicit domain result; exceptions must not be converted
    // indiscriminately into this value by a future WIT adapter.
    public static Quote shipping(Parcel parcel) {
        if (parcel.grams() <= 0 || parcel.grams() > 30_000) {
            return new Quote(false, 0, "invalid-weight");
        }
        if (!parcel.destination().equals("DE")) {
            return new Quote(false, 0, "unsupported-destination");
        }
        return new Quote(true, 500 + ((parcel.grams() + 999) / 1000) * 100, "");
    }

    public static int wordCount(String text) {
        int count = 0;
        boolean inWord = false;
        for (int offset = 0; offset < text.length();) {
            int codePoint = text.codePointAt(offset);
            boolean word = !Character.isWhitespace(codePoint);
            if (word && !inWord) {
                count++;
            }
            inWord = word;
            offset += Character.charCount(codePoint);
        }
        return count;
    }

    private static void require(boolean condition, String name) {
        if (!condition) {
            throw new AssertionError(name);
        }
    }

    public static void main(String[] args) {
        require(greet("Latvija").equals("Hello, Latvija!"), "greeting");
        require(wordCount("  hello\tworld\n\uD83D\uDE80 ") == 3, "word-count");
        require(wordCount("") == 0, "empty-word-count");
        require(shipping(new Parcel("DE", 1001)).equals(new Quote(true, 700, "")), "shipping-ok");
        require(shipping(new Parcel("DE", -1)).error().equals("invalid-weight"), "shipping-error");
        require(!shipping(new Parcel("US", 1)).ok(), "shipping-destination");
        require(Long.parseUnsignedLong("18446744073709551615") == -1L, "u64-bits");
        require(Long.toUnsignedString(-1L).equals("18446744073709551615"), "u64-text");
        require(Long.compareUnsigned(Long.MIN_VALUE, Long.MAX_VALUE) > 0, "u64-order");
        require(Long.parseLong("-9223372036854775808") == Long.MIN_VALUE, "s64-min");
        require(Long.parseLong("9223372036854775807") == Long.MAX_VALUE, "s64-max");
        String text = "R\u012bga\u0000\uD83D\uDE80\u00E9e\u0301";
        require(new String(text.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8).equals(text), "utf8");
        List<String> values = new ArrayList<>();
        values.add(text);
        values.add("");
        require(values.size() == 2 && values.get(0).equals(text), "list");
        int closed = 0;
        try {
            try {
                greet("");
            } finally {
                closed++;
            }
            throw new AssertionError("exception-not-thrown");
        } catch (IllegalArgumentException expected) {
            require(closed == 1, "exception-finally");
        }
        // This marker only witnesses these Java-level assertions when executed;
        // it is never evidence of canonical ABI, capabilities or node execution.
        System.out.println("java-feature-corpus:14-checks-passed");
    }
}

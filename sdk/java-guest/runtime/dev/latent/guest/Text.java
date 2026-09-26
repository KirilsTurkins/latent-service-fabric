package dev.latent.guest;

/** Stable Unicode White_Space semantics shared by the language tutorials. */
public final class Text {
    private Text() { }
    public static boolean whitespace(int value) {
        return value >= 9 && value <= 13 || value == 32 || value == 0x85 || value == 0xa0
            || value == 0x1680 || value >= 0x2000 && value <= 0x200a || value == 0x2028
            || value == 0x2029 || value == 0x202f || value == 0x205f || value == 0x3000;
    }
    public static String trim(String value) {
        int first = 0, end = value.length();
        while (first < end && whitespace(value.codePointAt(first))) first += Character.charCount(value.codePointAt(first));
        while (end > first && whitespace(value.codePointBefore(end))) end -= Character.charCount(value.codePointBefore(end));
        return value.substring(first, end);
    }
    public static int utf8Length(String value) { return value.getBytes(java.nio.charset.StandardCharsets.UTF_8).length; }
}

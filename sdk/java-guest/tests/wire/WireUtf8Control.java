package dev.latent.guest;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** Native reference equivalence only; this is not component execution evidence. */
public final class WireUtf8Control {
    private static int cases;

    private static String previous(byte[] bytes) {
        // The unchanged former Wire.text validity rule, independent of the new
        // byte validator: decode, reject unpaired UTF-16, then compare UTF-8.
        String value = new String(bytes, StandardCharsets.UTF_8);
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (Character.isHighSurrogate(character)) {
                if (++index == value.length() || !Character.isLowSurrogate(value.charAt(index))) {
                    throw new IllegalArgumentException();
                }
            } else if (Character.isLowSurrogate(character)) {
                throw new IllegalArgumentException();
            }
        }
        if (!Arrays.equals(bytes, value.getBytes(StandardCharsets.UTF_8))) {
            throw new IllegalArgumentException();
        }
        return value;
    }

    private static String standard(byte[] bytes) {
        try {
            return StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException invalid) {
            throw new IllegalArgumentException();
        }
    }

    private static String actual(byte[] bytes) {
        byte[] frame = new byte[4 + bytes.length];
        for (int index = 0; index < 4; index++) frame[index] = (byte) (bytes.length >>> (8 * index));
        System.arraycopy(bytes, 0, frame, 4, bytes.length);
        try (Wire.Reader reader = new Wire.Reader(frame)) {
            String value = reader.string();
            reader.finish();
            return value;
        } finally {
            for (byte value : frame) if (value != 0) throw new AssertionError("reader did not clear its frame");
        }
    }

    private static String result(byte[] bytes, int implementation) {
        try {
            return implementation == 0 ? actual(bytes) : implementation == 1 ? previous(bytes) : standard(bytes);
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }

    private static void check(byte... bytes) {
        String expected = result(bytes, 1);
        String standard = result(bytes, 2);
        String observed = result(bytes, 0);
        if (!(expected == null ? standard == null && observed == null
              : expected.equals(standard) && expected.equals(observed))) {
            throw new AssertionError("UTF-8 reference difference at case " + cases + ": "
                + Arrays.toString(Arrays.copyOf(bytes, Math.min(bytes.length, 8))));
        }
        cases++;
    }

    private static void boundAndWriterControls() {
        if (Wire.MAX_BYTES != 8 * 1024 * 1024 || Wire.MAX_ITEMS != 65536) {
            throw new AssertionError("original byte and item limits changed");
        }
        for (String invalid : new String[]{"\uD800", "\uDC00", "x\uD800x", "\uD800\uD800"}) {
            try {
                Wire.utf8(invalid);
                throw new AssertionError("writer accepted an unpaired surrogate");
            } catch (IllegalArgumentException expected) { }
        }
        for (long size : new long[]{Wire.MAX_BYTES + 1L, 0xFFFF_FFFFL}) {
            byte[] frame = new byte[4];
            for (int index = 0; index < 4; index++) frame[index] = (byte) (size >>> (8 * index));
            try (Wire.Reader reader = new Wire.Reader(frame)) {
                try {
                    reader.string();
                    throw new AssertionError("oversized or truncated string accepted");
                } catch (IllegalArgumentException expected) { }
            }
        }
    }

    public static void main(String[] args) {
        check();
        for (int first = 0; first < 256; first++) check((byte) first);
        int[] edges = {0, 0x7F, 0x80, 0x8F, 0x90, 0x9F, 0xA0, 0xBF, 0xC0, 0xFF};
        for (int first = 0; first < 256; first++) {
            for (int second : edges) check((byte) first, (byte) second);
        }
        for (int first = 0xE0; first <= 0xEF; first++) {
            for (int second : edges) for (int third : edges) {
                check((byte) first, (byte) second, (byte) third);
            }
        }
        for (int first = 0xF0; first <= 0xF4; first++) {
            for (int second : edges) for (int third : edges) for (int fourth : edges) {
                check((byte) first, (byte) second, (byte) third, (byte) fourth);
            }
        }
        int[] scalars = {0, 1, 0x7F, 0x80, 0x7FF, 0x800, 0xD7FF, 0xE000, 0xFEFF, 0xFFFD,
                         0xFFFE, 0xFFFF, 0x10000, 0x1F600, 0x10FFFE, 0x10FFFF};
        for (int scalar : scalars) {
            byte[] encoded = new String(Character.toChars(scalar)).getBytes(StandardCharsets.UTF_8);
            check(encoded);
            for (int length = 1; length < encoded.length; length++) check(Arrays.copyOf(encoded, length));
        }
        check((byte) 0xED, (byte) 0xA0, (byte) 0x80, (byte) 0xED, (byte) 0xB0, (byte) 0x80);
        check("ASCII\u0000\u007F\u0080\u07FF\u0800\uD7FF\uE000\uFFFF\uD800\uDC00\uDBFF\uDFFF".getBytes(StandardCharsets.UTF_8));
        for (int length : new int[]{3, 43692, 87384}) {
            byte[] ascii = new byte[length];
            Arrays.fill(ascii, (byte) 'A');
            check(ascii);
        }
        boundAndWriterControls();
        System.out.println("WIRE_UTF8_SOURCE_CONTROL PASS cases=" + cases
            + ";previous-rule;jdk-report;scalar-boundaries;overlong-surrogate-truncation-range;"
            + "large-ascii;original-bounds;writer-surrogates;COMPONENT_QUALIFICATION=pending");
    }
}

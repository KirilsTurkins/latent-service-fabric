package outside.resourcechild;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public final class Data {
    private Data() {}

    public static String read(String mode) {
        try {
            if (mode.equals("text")) {
                try (InputStream input = Data.class.getResourceAsStream("utf8.txt")) {
                    if (input == null) throw new IllegalStateException("text-missing");
                    return "text=" + new String(input.readAllBytes(), StandardCharsets.UTF_8);
                }
            }
            if (mode.equals("binary")) {
                try (InputStream input = Data.class.getClassLoader().getResourceAsStream("outside/resourcechild/binary.bin")) {
                    if (input == null || !Arrays.equals(input.readAllBytes(), new byte[] {0, -1, -128, 65, 13, 10}))
                        throw new IllegalStateException("binary-bytes");
                    return "binary=00ff80410d0a";
                }
            }
            if (mode.equals("empty")) {
                try (InputStream input = Data.class.getResourceAsStream("empty.bin")) {
                    if (input == null || input.readAllBytes().length != 0 || input.read() != -1)
                        throw new IllegalStateException("empty-bytes");
                    return "empty=0";
                }
            }
            if (mode.equals("missing")) {
                if (Data.class.getResourceAsStream("missing.bin") != null
                        || Data.class.getClassLoader().getResourceAsStream("outside/resourcechild/missing.bin") != null)
                    throw new IllegalStateException("missing-fallback");
                return "missing=null";
            }
            if (mode.equals("independent")) {
                try (InputStream first = Data.class.getResourceAsStream("binary.bin");
                        InputStream second = Data.class.getResourceAsStream("binary.bin")) {
                    if (first == null || second == null || first == second || first.read() != 0
                            || first.read() != 255 || second.read() != 0 || second.available() != 5)
                        throw new IllegalStateException("stream-positions");
                    first.close();
                    if (second.read() != 255 || second.available() != 4)
                        throw new IllegalStateException("stream-close-alias");
                    return "independent=2,2|close=other-readable";
                }
            }
            if (mode.equals("null")) {
                try {
                    Data.class.getClassLoader().getResourceAsStream(null);
                } catch (NullPointerException expected) {
                    return "null=null-pointer";
                }
                throw new IllegalStateException("null-name-accepted");
            }
            if (mode.equals("unicode")) {
                try (InputStream input = Data.class.getClassLoader().getResourceAsStream("unicode/\u96ea.txt")) {
                    if (input == null) throw new IllegalStateException("unicode-name-missing");
                    return "unicode=" + new String(input.readAllBytes(), StandardCharsets.UTF_8);
                }
            }
            throw new IllegalArgumentException("resource-mode");
        } catch (IOException error) {
            throw new IllegalStateException("resource-io", error);
        }
    }
}

package outside.resourceruntimedata;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public final class Data implements AutoCloseable {
    public final InputStream first;
    public final InputStream second;
    private final InputStream empty;

    public Data() {
        try (InputStream text = Data.class.getResourceAsStream("utf8.txt")) {
            if (text == null || !"Gr\u00fc\u00dfe\0\u96ea\n".equals(new String(text.readAllBytes(), StandardCharsets.UTF_8))) {
                throw new IllegalStateException("resource-text");
            }
        } catch (IOException error) { throw new IllegalStateException("resource-text-io", error); }
        first = Data.class.getResourceAsStream("binary.bin");
        second = Data.class.getClassLoader().getResourceAsStream("outside/resourceruntimedata/binary.bin");
        empty = Data.class.getResourceAsStream("empty.bin");
        if (first == null || second == null || first == second || empty == null) {
            throw new IllegalStateException("resource-stream-identity");
        }
    }

    public void verifyEmpty() {
        try {
            if (empty.readAllBytes().length != 0 || empty.read() != -1) throw new IllegalStateException("resource-empty");
        } catch (IOException error) { throw new IllegalStateException("resource-empty-io", error); }
    }

    public static int read(InputStream input) {
        try { return input.read(); }
        catch (IOException error) { throw new IllegalStateException("resource-read-io", error); }
    }

    public static void remainder(InputStream input) {
        try {
            if (!Arrays.equals(input.readAllBytes(), new byte[] {-128, 65, 13, 10}) || input.read() != -1) {
                throw new IllegalStateException("resource-binary-remainder");
            }
        } catch (IOException error) { throw new IllegalStateException("resource-remainder-io", error); }
    }

    public void closeFirst() {
        try { first.close(); }
        catch (IOException error) { throw new IllegalStateException("resource-first-close", error); }
    }

    @Override public void close() {
        try { first.close(); second.close(); empty.close(); }
        catch (IOException error) { throw new IllegalStateException("resource-close", error); }
    }
}

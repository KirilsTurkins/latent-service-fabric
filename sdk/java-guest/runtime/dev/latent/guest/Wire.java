package dev.latent.guest;

import java.util.ArrayList;
import java.util.Arrays;
import org.teavm.interop.Address;
import org.teavm.interop.Import;

/** Private bounded bridge to maintained wit-bindgen C, not a host wire protocol. */
public final class Wire {
    public static final int MAX_BYTES = 8 * 1024 * 1024;
    public static final int MAX_ITEMS = 65536;
    private Wire() { }
    @Import(name = "lsf_java_alloc") private static native Address allocate(int length);
    @Import(name = "lsf_java_free") private static native void free(Address pointer);
    @Import(name = "lsf_java_host") private static native Address host(int operation, Address bytes, int length);
    public static void require(boolean condition) {
        if (!condition) throw new IllegalArgumentException("invalid or oversized Java WIT value");
    }
    public static byte[] utf8(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isHighSurrogate(c)) {
                require(++i < value.length() && Character.isLowSurrogate(value.charAt(i)));
            } else require(!Character.isLowSurrogate(c));
        }
        byte[] encoded = value.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        require(encoded.length <= MAX_BYTES);
        return encoded;
    }
    private static String text(byte[] bytes) {
        // Component canonical strings already guarantee UTF-8. Recheck the
        // private bridge rather than silently replacing malformed sequences.
        String value = new String(bytes, java.nio.charset.StandardCharsets.UTF_8);
        byte[] encoded = utf8(value);
        try { require(Arrays.equals(bytes, encoded)); return value; }
        finally { Arrays.fill(encoded, (byte) 0); }
    }
    public static final class Reader implements AutoCloseable {
        private final byte[] data;
        private int cursor;
        private boolean closed;
        public Reader(byte[] data) { require(data.length <= MAX_BYTES); this.data = data; }
        public static Reader copy(Address pointer, int length) {
            require(length >= 0 && length <= MAX_BYTES);
            byte[] result = new byte[length];
            for (int i = 0; i < length; i++) result[i] = pointer.add(i).getByte();
            return new Reader(result);
        }
        public long integer(int width) {
            require(!closed && width > 0 && width <= 8 && width <= data.length - cursor);
            long value = 0;
            for (int i = 0; i < width; i++) value |= (data[cursor++] & 255L) << (i * 8);
            return value;
        }
        public int count() {
            long count = integer(4);
            require(count <= MAX_ITEMS);
            return (int) count;
        }
        public boolean bool() { long value = integer(1); require(value <= 1); return value != 0; }
        public byte[] bytes() {
            long size = integer(4);
            require(size <= MAX_BYTES && size <= data.length - cursor);
            byte[] result = Arrays.copyOfRange(data, cursor, cursor + (int) size);
            cursor += (int) size;
            return result;
        }
        public String string() {
            byte[] bytes = bytes();
            try { return text(bytes); } finally { Arrays.fill(bytes, (byte) 0); }
        }
        public void finish() { require(!closed && cursor == data.length); }
        @Override public void close() { Arrays.fill(data, (byte) 0); closed = true; }
    }
    public static final class Writer implements AutoCloseable {
        private byte[] data = new byte[128];
        private int length;
        private boolean closed;
        private final ArrayList<Resource> borrows = new ArrayList<>();
        private void reserve(int bytes) {
            require(!closed && bytes >= 0 && bytes <= MAX_BYTES - length);
            if (bytes > data.length - length) {
                byte[] previous = data;
                data = Arrays.copyOf(previous, Math.max(length + bytes, Math.min(MAX_BYTES, data.length * 2)));
                Arrays.fill(previous, (byte) 0);
            }
        }
        public void integer(long value, int width) {
            require(width > 0 && width <= 8); reserve(width);
            for (int i = 0; i < width; i++) data[length++] = (byte) (value >>> (i * 8));
        }
        public void unsigned(long value, int width) {
            require(width < 8 && value >= 0 && value < (1L << (width * 8)));
            integer(value, width);
        }
        public void count(int value) { require(value >= 0 && value <= MAX_ITEMS); integer(value, 4); }
        public void bool(boolean value) { integer(value ? 1 : 0, 1); }
        public void bytes(byte[] value) {
            integer(value.length, 4); reserve(value.length);
            System.arraycopy(value, 0, data, length, value.length); length += value.length;
        }
        public void string(String value) {
            byte[] encoded = utf8(value);
            try { bytes(encoded); } finally { Arrays.fill(encoded, (byte) 0); }
        }
        public void resource(Resource value, boolean own) {
            if (own) integer(value.consume(), 4);
            else {
                int handle = value.borrow();
                try { borrows.add(value); } catch (Throwable failure) { value.releaseBorrow(); throw failure; }
                integer(handle, 4);
            }
        }
        public Reader call(int operation) {
            require(!closed);
            // The array remains strongly live across this native call. No Java
            // scheduler or asynchronous callback may run inside the profile.
            Address result = host(operation, Address.ofData(data), length);
            try { return Reader.copy(result.add(4), result.getInt()); }
            finally { free(result); }
        }
        public Address nativeResult() {
            require(!closed && borrows.isEmpty());
            Address result = allocate(length);
            for (int i = 0; i < length; i++) result.add(4 + i).putByte(data[i]);
            return result;
        }
        @Override public void close() {
            if (closed) return;
            for (Resource value : borrows) value.releaseBorrow();
            borrows.clear(); Arrays.fill(data, (byte) 0); closed = true;
        }
    }
}

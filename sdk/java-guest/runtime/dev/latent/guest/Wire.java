package dev.latent.guest;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import java.util.Arrays;
import org.teavm.interop.Address;
import org.teavm.interop.Import;

/** Private bounded bridge to maintained wit-bindgen C, not a host wire protocol. */
public final class Wire {
    public interface HostFunction {
        Address call(int operation, Address bytes, int length);
        default Address callOwned(int operation, byte[] bytes, int length) {
            return call(operation, Address.ofData(bytes), length);
        }
        default boolean retainsBorrowedResources() { return false; }
    }
    public static final int NETWORK_READ = 1, NETWORK_WRITE = 2, NETWORK_READY = 3, NETWORK_INSPECT = 4;
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
        for (int cursor = 0; cursor < bytes.length;) {
            int first = bytes[cursor++] & 255;
            if (first < 128) continue;
            // Exclude stray continuations, overlong two-byte forms and values
            // beyond the Unicode scalar range before reading any continuation.
            require(first >= 0xC2 && first <= 0xF4);
            int remaining = first <= 0xDF ? 1 : first <= 0xEF ? 2 : 3;
            require(remaining <= bytes.length - cursor);
            int second = bytes[cursor++] & 255;
            require(second >= 0x80 && second <= 0xBF);
            if (first == 0xE0) require(second >= 0xA0);
            if (first == 0xED) require(second <= 0x9F);
            if (first == 0xF0) require(second >= 0x90);
            if (first == 0xF4) require(second <= 0x8F);
            for (int index = 1; index < remaining; index++) {
                require((bytes[cursor++] & 0xC0) == 0x80);
            }
        }
        // Validation needs no duplicate encoder buffers. Decode the reviewed
        // bytes once; Writer.utf8 still validates outbound UTF-16 surrogates.
        return new String(bytes, java.nio.charset.StandardCharsets.UTF_8);
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
        // Each rooted writer belongs to an already admitted async Call. The
        // intrusive list needs no allocation after native acceptance becomes
        // uncertain. A retained writer and its inputs die with the Store.
        private static final Object INPUT_LOCK = new Object();
        private static Writer rootedInputs;
        private Writer rootPrevious, rootNext;
        private byte[] data = new byte[128];
        private int length;
        private boolean closed;
        private boolean started;
        private boolean retainedUncertain;
        private final int direction;
        private final Bindings.BorrowPermit permit;
        private final ArrayList<Resource> borrows = new ArrayList<>();
        public Writer() { this.permit = null; this.direction = 0; }
        public Writer(Bindings.BorrowPermit permit) {
            require(permit != null);
            int direction = permit.direction();
            require(direction >= 0 && direction <= NETWORK_INSPECT);
            this.permit = permit;
            this.direction = direction;
        }
        private void reserve(int bytes) {
            require(!closed && !started && bytes >= 0 && bytes <= MAX_BYTES - length);
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
            require(!closed && !started && !retainedUncertain);
            if (own) integer(value.consume(), 4);
            else {
                int handle = value.borrow(direction);
                try { borrows.add(value); } catch (Throwable failure) { value.releaseBorrow(direction); throw failure; }
                integer(handle, 4);
            }
        }
        public Reader call(int operation) {
            require(!closed && !started);
            if (permit != null) require(permit.authorizes(null, operation));
            started = true;
            return result(host(operation, Address.ofData(data), length), false);
        }
        public Reader call(HostFunction function, int operation, boolean allowPendingCancellation) {
            require(!closed && !started);
            if (permit == null) require(borrows.isEmpty());
            else require(permit.authorizes(function, operation));
            started = true;
            // Root before entering the exact admitted native call. A suspended
            // frame alone is insufficient if a catchable exception unwinds it.
            boolean rooted = permit != null;
            if (rooted) rootInput();
            try {
                Address result = rooted ? function.callOwned(operation, data, length)
                        : function.call(operation, Address.ofData(data), length);
                return result(result, allowPendingCancellation);
            } catch (RuntimeException | Error failure) {
                // Do not clear the array or its resource roots while native
                // acceptance remains uncertain. Retain the existing Wait too.
                if (rooted && function.retainsBorrowedResources()) retainedUncertain = true;
                throw failure;
            } finally {
                if (rooted && !retainedUncertain) unrootInput();
            }
        }
        private void rootInput() {
            synchronized (INPUT_LOCK) {
                rootNext = rootedInputs;
                if (rootNext != null) rootNext.rootPrevious = this;
                rootedInputs = this;
            }
        }
        private void unrootInput() {
            synchronized (INPUT_LOCK) {
                if (rootPrevious == null) rootedInputs = rootNext;
                else rootPrevious.rootNext = rootNext;
                if (rootNext != null) rootNext.rootPrevious = rootPrevious;
                rootPrevious = null;
                rootNext = null;
            }
        }
        private Reader result(Address result, boolean allowPendingCancellation) {
            if (allowPendingCancellation && result.toInt() == 0) return null;
            require(result.toInt() != 0);
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
            if (!retainedUncertain) {
                for (Resource value : borrows) value.releaseBorrow(direction);
                borrows.clear(); Arrays.fill(data, (byte) 0);
            }
            closed = true;
        }
    }
}

package dev.latent.guest;

/** Explicit owner; clears the adopted array, never logs or converts it to text. */
public final class SensitiveBytes implements AutoCloseable {
    private final byte[] value;
    private boolean closed;
    public SensitiveBytes(byte[] value) { this.value = java.util.Objects.requireNonNull(value); }
    public byte[] borrow() {
        if (closed) throw new IllegalStateException("bytes are closed");
        return value;
    }
    @Override public void close() { java.util.Arrays.fill(value, (byte) 0); closed = true; }
}

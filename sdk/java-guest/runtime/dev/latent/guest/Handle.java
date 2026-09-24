package dev.latent.guest;

/** Activation-local owner for WIT APIs that use opaque u64 handles. */
public final class Handle implements AutoCloseable {
    @FunctionalInterface public interface Releaser { void release(Unsigned64 handle); }
    private final Unsigned64 value;
    private final Releaser releaser;
    private boolean closed;
    public Handle(Unsigned64 value, Releaser releaser) {
        this.value = java.util.Objects.requireNonNull(value);
        this.releaser = java.util.Objects.requireNonNull(releaser);
    }
    public Unsigned64 borrow() {
        if (closed) throw new IllegalStateException("handle is closed or consumed");
        return value;
    }
    /** Consume before seal/transfer; failure must never restore authority. */
    public Unsigned64 consume() { Unsigned64 result = borrow(); closed = true; return result; }
    @Override public void close() {
        if (!closed) releaser.release(consume());
    }
}

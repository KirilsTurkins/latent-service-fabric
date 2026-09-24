package dev.latent.guest;

/** Canonical owned resource. No finalizer, background work or automatic retry. */
public abstract class Resource implements AutoCloseable {
    private final int handle;
    private final int destructor;
    private boolean closed;
    private boolean borrowed;
    protected Resource(int handle, int destructor) { this.handle = handle; this.destructor = destructor; }
    final int borrow() {
        if (closed || borrowed) throw new IllegalStateException("resource is closed or already borrowed");
        borrowed = true;
        return handle;
    }
    final void releaseBorrow() {
        if (!borrowed || closed) throw new IllegalStateException("invalid resource borrow release");
        borrowed = false;
    }
    final int consume() {
        if (closed || borrowed) throw new IllegalStateException("resource is closed or borrowed");
        closed = true;
        return handle;
    }
    @Override public final void close() {
        if (closed) return;
        int owned = consume();
        try (Wire.Writer arguments = new Wire.Writer()) {
            arguments.integer(owned, 4);
            try (Wire.Reader result = arguments.call(destructor)) { result.finish(); }
        }
    }
}

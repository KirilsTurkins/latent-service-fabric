package dev.latent.guest;

/** Canonical owned resource. No finalizer, background work or automatic retry. */
public abstract class Resource implements AutoCloseable {
    private final int handle;
    private final int destructor;
    private boolean closed;
    private final boolean directionalBorrows;
    private int borrowed;
    protected Resource(int handle, int destructor) { this(handle, destructor, false); }
    protected Resource(int handle, int destructor, boolean directionalBorrows) {
        this.handle = handle; this.destructor = destructor; this.directionalBorrows = directionalBorrows;
    }
    final int borrow() {
        return borrow(0);
    }
    final int borrow(int direction) {
        if (!directionalBorrows) direction = 0;
        if (direction < 0 || direction > 4) throw new IllegalArgumentException("unknown resource borrow direction");
        int selected = 1 << direction;
        synchronized (this) {
            if (!closed && (direction == 0 ? borrowed == 0 : (borrowed & (1 | selected)) == 0)) {
                borrowed |= selected;
                return handle;
            }
        }
        throw new IllegalStateException("resource is closed or already borrowed");
    }
    final void releaseBorrow() {
        releaseBorrow(0);
    }
    final void releaseBorrow(int direction) {
        if (!directionalBorrows) direction = 0;
        if (direction < 0 || direction > 4) throw new IllegalArgumentException("unknown resource borrow direction");
        int selected = 1 << direction;
        synchronized (this) {
            if (!closed && (borrowed & selected) != 0) {
                borrowed &= ~selected;
                return;
            }
        }
        throw new IllegalStateException("invalid resource borrow release");
    }
    final int consume() {
        synchronized (this) {
            if (!closed && borrowed == 0) {
                closed = true;
                return handle;
            }
        }
        throw new IllegalStateException("resource is closed or borrowed");
    }
    @Override public final void close() {
        int owned = 0;
        boolean blocked = false;
        synchronized (this) {
            if (closed) return;
            if (borrowed != 0) blocked = true;
            else { closed = true; owned = handle; }
        }
        if (blocked) throw new IllegalStateException("resource is closed or borrowed");
        try (Wire.Writer arguments = new Wire.Writer()) {
            arguments.integer(owned, 4);
            try (Wire.Reader result = arguments.call(destructor)) { result.finish(); }
        }
    }
}

package dev.latent.guest.runtime;

import org.teavm.interop.Address;

/** The existing fiber profile keeps its synchronous canonical import ABI. */
public final class HostCalls {
    private HostCalls() { }
    public static boolean enabled() { return false; }
    public static boolean poll() { return false; }
    public static boolean waitAny() { return false; }
    public static final class Call implements AutoCloseable {
        private Call() { }
        public Address call(int operation, Address bytes, int length) {
            throw new IllegalStateException("fiber-aware-host-import-profile-not-selected");
        }
        @Override public void close() { }
    }
    public static Call admit() {
        throw new IllegalStateException("fiber-aware-host-import-profile-not-selected");
    }
    public static Address waitRoot(int operation, Address bytes, int length) {
        throw new IllegalStateException("fiber-aware-host-import-profile-not-selected");
    }
}

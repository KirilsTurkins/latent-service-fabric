package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import java.util.ArrayList;
import org.teavm.interop.Address;
import org.teavm.interop.Async;
import org.teavm.interop.AsyncCallback;
import org.teavm.interop.Import;
import org.teavm.runtime.Fiber;

/** Selected SDK profile; ordinary callers keep their original WIT API. */
public final class HostCalls {
    private static final ArrayList<Call> pending = new ArrayList<>();
    private HostCalls() { }
    public static final class Call implements AutoCloseable {
        Address nativeCall;
        AsyncCallback<Integer> callback;
        Activation.Lease wait;
        boolean invoked;
        boolean closed;
        boolean complete;
        private Call() { }
        public Address call(int operation, Address bytes, int length) {
            if (closed || invoked) throw new IllegalStateException("host-import-call-already-used");
            // Native acceptance becomes uncertain once suspension is entered.
            // A later exception must not refund this reservation prematurely.
            invoked = true;
            return Address.fromInt(suspend(operation, bytes, length, this));
        }
        @Override public void close() {
            if (closed) return;
            closed = true;
            if (!invoked || complete) wait.close();
        }
    }
    @Import(name = "lsf_java_async_begin") private static native Address begin(int operation, Address bytes, int length);
    @Import(name = "lsf_java_async_state") private static native int state(Address call);
    @Import(name = "lsf_java_async_take") private static native Address take(Address call, int cancelledRootWait);
    @Import(name = "lsf_java_async_poll") private static native void pollNative();
    @Import(name = "lsf_java_async_wait") private static native void waitNative();
    @Import(name = "lsf_java_async_cancel_root_wait") private static native int cancelRootWait(Address call);
    public static boolean enabled() { return true; }

    public static Call admit() {
        if (Fiber.current() == null) throw new IllegalStateException("host-import-needs-owned-java-fiber");
        Call owner = new Call();
        owner.wait = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Wait);
        return owner;
    }
    @Async private static native int suspend(int operation, Address bytes, int length, Call owner);
    private static void suspend(int operation, Address bytes, int length, Call owner, AsyncCallback<Integer> callback) {
        owner.callback = callback;
        owner.nativeCall = begin(operation, bytes, length);
        if (state(owner.nativeCall) == 2) finish(owner);
        else pending.add(owner);
    }
    private static void finish(Call owner) {
        Address result = take(owner.nativeCall, 0);
        owner.nativeCall = Address.fromInt(0);
        owner.complete = true;
        owner.callback.complete(result.toInt());
    }
    public static boolean poll() {
        pollNative();
        boolean resumed = false;
        for (int index = 0; index < pending.size();) {
            Call owner = pending.get(index);
            int observed = state(owner.nativeCall);
            if (observed < 2) { index++; continue; }
            if (observed != 2) throw new IllegalStateException("unexpected-host-import-cancellation");
            pending.remove(index);
            finish(owner);
            resumed = true;
        }
        return resumed;
    }
    private static boolean readyCaller() {
        for (Call owner : pending) if (state(owner.nativeCall) >= 2) return true;
        return false;
    }
    public static boolean waitAny() {
        if (pending.isEmpty()) return false;
        if (!readyCaller()) waitNative();
        return true;
    }
    public static Address waitRoot(int operation, Address bytes, int length) {
        if (Fiber.current() != null) throw new IllegalStateException("root-host-wait-outside-java-fiber-required");
        Address call = begin(operation, bytes, length);
        while (state(call) < 2) {
            if (readyCaller()) {
                cancelRootWait(call);
                while (state(call) < 2) waitNative();
                return take(call, 1);
            }
            waitNative();
        }
        if (state(call) != 2) throw new IllegalStateException("unexpected-root-host-wait-cancellation");
        return take(call, 0);
    }
}

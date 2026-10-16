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
    private static final ArrayList<Pending> pending = new ArrayList<>();
    private HostCalls() { }
    private static final class Pending {
        Address nativeCall;
        AsyncCallback<Integer> callback;
        boolean complete;
    }
    @Import(name = "lsf_java_async_begin") private static native Address begin(int operation, Address bytes, int length);
    @Import(name = "lsf_java_async_state") private static native int state(Address call);
    @Import(name = "lsf_java_async_take") private static native Address take(Address call, int cancelledRootWait);
    @Import(name = "lsf_java_async_poll") private static native void pollNative();
    @Import(name = "lsf_java_async_wait") private static native void waitNative();
    @Import(name = "lsf_java_async_cancel_root_wait") private static native int cancelRootWait(Address call);
    public static boolean enabled() { return true; }

    public static Address call(int operation, Address bytes, int length) {
        if (Fiber.current() == null) throw new IllegalStateException("host-import-needs-owned-java-fiber");
        Pending owner = new Pending();
        var wait = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Wait);
        try { return Address.fromInt(suspend(operation, bytes, length, owner)); }
        finally {
            // An exception after uncertain native acceptance retains the owner
            // until Store destruction. Only an actual terminal take refunds it.
            if (owner.complete) wait.close();
        }
    }
    @Async private static native int suspend(int operation, Address bytes, int length, Pending owner);
    private static void suspend(int operation, Address bytes, int length, Pending owner, AsyncCallback<Integer> callback) {
        owner.callback = callback;
        owner.nativeCall = begin(operation, bytes, length);
        if (state(owner.nativeCall) == 2) finish(owner);
        else pending.add(owner);
    }
    private static void finish(Pending owner) {
        Address result = take(owner.nativeCall, 0);
        owner.nativeCall = Address.fromInt(0);
        owner.complete = true;
        owner.callback.complete(result.toInt());
    }
    public static boolean poll() {
        pollNative();
        boolean resumed = false;
        for (int index = 0; index < pending.size();) {
            Pending owner = pending.get(index);
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
        for (Pending owner : pending) if (state(owner.nativeCall) >= 2) return true;
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

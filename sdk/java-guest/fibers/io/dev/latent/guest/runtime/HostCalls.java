package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import dev.latent.guest.Wire;
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
    public static final class Call implements AutoCloseable, Wire.HostFunction {
        Address nativeCall;
        AsyncCallback<Integer> callback;
        Activation.Lease wait;
        boolean invoked;
        boolean closed;
        boolean complete;
        Address scratch;
        private Call() { }
        @Override public Address call(int operation, Address bytes, int length) {
            if (closed || invoked) throw new IllegalStateException("host-import-call-already-used");
            // Native acceptance becomes uncertain once suspension is entered.
            // A later exception must not refund this reservation prematurely.
            invoked = true;
            return Address.fromInt(suspend(operation, bytes, length, this));
        }
        @Override public Address callOwned(int operation, byte[] bytes, int length) {
            if (closed || invoked) throw new IllegalStateException("host-import-call-already-used");
            if (bytes == null || length < 0 || length > bytes.length || length > Wire.MAX_BYTES)
                throw new IllegalArgumentException("host-import-invalid-owned-input");
            // Once entered, retain the existing Wait and borrowed resources on
            // any uncertain exception. The copy is bounded by the same wire cap.
            invoked = true;
            Address frame = null;
            boolean transferred = false;
            try {
                frame = allocateScratch(length);
                // Each access remains a managed Java array access. Only the
                // independent native frame address reaches the asynchronous bridge.
                for (int i = 0; i < length; ++i) frame.add(4 + i).putByte(bytes[i]);
                Address payload = frame.add(4);
                if (closed) throw new IllegalStateException("host-import-call-already-used");
                scratch = frame;
                transferred = true;
                return Address.fromInt(suspendOwned(operation, payload, length, this));
            } catch (Throwable failure) {
                // Before handoff there can be no native borrower. After handoff,
                // keep the frame until terminal take or Store teardown.
                if (!transferred && frame != null) {
                    try { freeScratch(frame); } catch (Throwable unavailable) { }
                }
                throw failure;
            }
        }
        private void releaseScratch() {
            Address frame = scratch;
            scratch = null;
            if (frame != null) freeScratch(frame);
        }
        @Override public boolean retainsBorrowedResources() { return invoked && !complete; }
        @Override public void close() {
            if (closed) return;
            closed = true;
            if (!invoked || complete) wait.close();
        }
    }
    @Import(name = "lsf_java_alloc") private static native Address allocateScratch(int length);
    @Import(name = "lsf_java_free") private static native void freeScratch(Address frame);
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
    @Async private static native int suspendOwned(int operation, Address bytes, int length, Call owner);
    private static void suspendOwned(int operation, Address bytes, int length, Call owner, AsyncCallback<Integer> callback) {
        owner.callback = callback;
        owner.nativeCall = begin(operation, bytes, length);
        if (state(owner.nativeCall) == 2) finish(owner);
        else pending.add(owner);
    }
    private static void finish(Call owner) {
        Address result = take(owner.nativeCall, 0);
        owner.nativeCall = Address.fromInt(0);
        // take() has reached a terminal state; native input can now be erased.
        owner.releaseScratch();
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

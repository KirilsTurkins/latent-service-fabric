package dev.latent.guest.runtime;

import dev.latent.guest.Wire;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.Arrays;
import org.teavm.interop.Address;
import org.teavm.interop.AsyncCallback;

/** Actual Call source with only native and suspension boundaries replaced by deterministic JDK fakes. */
public final class NetworkScratchControl {
    static byte[] expected;
    static Address frame;
    static RuntimeException copyFailure, entryFailure, freeFailure, takeFailure, allocFailure, callbackFailure;
    static HostCalls.Call closeDuringCopy;
    static int failAt, closeAt, writes, allocs, frees, begins, takes, callbackCount, nativeState;
    static boolean released, took;

    private static void require(boolean value) {
        if (!value) throw new AssertionError("scratch-lifecycle");
    }
    private static void reset(byte[] input) {
        expected = input; frame = null; copyFailure = entryFailure = freeFailure = takeFailure = allocFailure = callbackFailure = null;
        closeDuringCopy = null; failAt = closeAt = -1; writes = allocs = frees = begins = takes = callbackCount = 0;
        nativeState = 2; released = took = false;
    }
    public static Address allocate(int length) {
        allocs++;
        if (allocFailure != null) throw allocFailure;
        frame = new Address(new byte[length + 4], 0);
        frame.data[0] = (byte) length;
        frame.data[1] = (byte) (length >>> 8);
        frame.data[2] = (byte) (length >>> 16);
        frame.data[3] = (byte) (length >>> 24);
        return frame;
    }
    public static void write(Address target, byte value) {
        int index = writes++;
        if (index == closeAt) closeDuringCopy.close();
        if (index == failAt) throw copyFailure;
        target.data[target.offset] = value;
    }
    public static void free(Address value) {
        require(value.data == frame.data && value.offset == 0 && !released);
        frees++;
        if (freeFailure != null) throw freeFailure;
        Arrays.fill(value.data, (byte) 0); released = true;
    }
    public static Address begin(int operation, Address input, int length) {
        begins++;
        require(input.data == frame.data && input.offset == 4 && length == expected.length && !released);
        for (int i = 0; i < length; i++) require(input.data[4 + i] == expected[i]);
        return Address.fromInt(17);
    }
    public static int state(Address call) { return nativeState; }
    public static Address take(Address call, int cancelled) {
        takes++; require(nativeState == 2 && !released);
        if (takeFailure != null) throw takeFailure;
        took = true;
        return Address.fromInt(77);
    }
    @SuppressWarnings("unchecked")
    private static <T extends Throwable> void rethrow(Throwable value) throws T { throw (T) value; }
    public static int enter(int operation, Address input, int length, HostCalls.Call owner) {
        if (entryFailure != null) throw entryFailure;
        try {
            Method callback = HostCalls.class.getDeclaredMethod("suspendOwned", int.class, Address.class,
                    int.class, HostCalls.Call.class, AsyncCallback.class);
            callback.setAccessible(true);
            AsyncCallback<Integer> completion = value -> {
                require(took && released && owner.scratch == null && owner.complete && value == 77);
                callbackCount++;
                if (callbackFailure != null) throw callbackFailure;
            };
            callback.invoke(null, operation, input, length, owner, completion);
            return 77;
        } catch (InvocationTargetException failure) {
            NetworkScratchControl.<RuntimeException>rethrow(failure.getCause());
            throw new AssertionError("unreachable");
        } catch (ReflectiveOperationException failure) {
            throw new AssertionError(failure);
        }
    }
    private static void expect(RuntimeException marker, Runnable body) {
        try { body.run(); throw new AssertionError("expected failure"); }
        catch (RuntimeException actual) { require(actual == marker); }
    }
    private static void invalid(HostCalls.Call owner, byte[] bytes, int length) {
        try { owner.callOwned(1, bytes, length); throw new AssertionError("invalid input accepted"); }
        catch (IllegalArgumentException expected) { require(!owner.invoked && allocs == 0); }
    }
    private static void testInvalid() {
        reset(new byte[0]);
        HostCalls.Call owner = HostCalls.admit();
        invalid(owner, null, 0); invalid(owner, new byte[1], -1); invalid(owner, new byte[1], 2);
        invalid(owner, new byte[Wire.MAX_BYTES + 1], Wire.MAX_BYTES + 1);
        owner.close(); require(owner.wait.closed && !owner.retainsBorrowedResources());
    }
    private static void testTerminal(byte[] input, boolean pending) {
        reset(input); nativeState = pending ? 0 : 2;
        HostCalls.Call owner = HostCalls.admit();
        owner.callOwned(2, input, input.length);
        require(allocs == 1 && begins == 1 && writes == input.length);
        if (pending) {
            require(!released && !owner.complete && owner.scratch != null && owner.retainsBorrowedResources());
            require(frees == 0 && takes == 0 && callbackCount == 0);
            nativeState = 2; require(HostCalls.poll());
        }
        require(owner.complete && owner.scratch == null && released && frees == 1 && takes == 1 && callbackCount == 1);
        require(!owner.retainsBorrowedResources());
        owner.close(); require(owner.wait.closed);
        for (byte value : frame.data) require(value == 0);
    }
    private static void testCopyFailure(boolean cleanupFails) {
        reset(new byte[] { 4, 5, 6 });
        copyFailure = new IllegalStateException("copy");
        if (cleanupFails) freeFailure = new IllegalStateException("free");
        failAt = 1;
        HostCalls.Call owner = HostCalls.admit();
        expect(copyFailure, () -> owner.callOwned(3, expected, expected.length));
        require(allocs == 1 && begins == 0 && frees == 1 && owner.scratch == null);
        require(released != cleanupFails && owner.retainsBorrowedResources());
        owner.close(); require(!owner.wait.closed);
    }
    private static void testAllocationFailure() {
        reset(new byte[] { 5 });
        allocFailure = new IllegalStateException("allocate");
        HostCalls.Call owner = HostCalls.admit();
        expect(allocFailure, () -> owner.callOwned(5, expected, expected.length));
        require(allocs == 1 && begins == 0 && frees == 0 && owner.scratch == null);
        require(owner.retainsBorrowedResources()); owner.close(); require(!owner.wait.closed);
    }
    private static void testClosedDuringCopy() {
        reset(new byte[] { 3, 4, 5 });
        HostCalls.Call owner = HostCalls.admit();
        closeDuringCopy = owner; closeAt = 1;
        try { owner.callOwned(6, expected, expected.length); throw new AssertionError("close accepted"); }
        catch (IllegalStateException expected) { require("host-import-call-already-used".equals(expected.getMessage())); }
        require(begins == 0 && frees == 1 && released && owner.scratch == null);
        require(owner.retainsBorrowedResources() && !owner.wait.closed);
    }
    private static void testTerminalFailure(boolean failCallback) {
        reset(new byte[] { 11 });
        RuntimeException marker = new IllegalStateException(failCallback ? "callback" : "free");
        if (failCallback) callbackFailure = marker; else freeFailure = marker;
        HostCalls.Call owner = HostCalls.admit();
        expect(marker, () -> owner.callOwned(7, expected, expected.length));
        require(takes == 1 && took && frees == 1 && owner.scratch == null);
        require(released == failCallback && owner.complete == failCallback);
        require(owner.retainsBorrowedResources() != failCallback);
        owner.close(); require(owner.wait.closed == failCallback);
    }
    private static void testUncertain(boolean failTake) {
        reset(new byte[] { 12, 13 });
        RuntimeException marker = new IllegalStateException(failTake ? "take" : "entry");
        if (failTake) takeFailure = marker; else entryFailure = marker;
        HostCalls.Call owner = HostCalls.admit();
        expect(marker, () -> owner.callOwned(4, expected, expected.length));
        require(begins == (failTake ? 1 : 0) && frees == 0 && !released && owner.scratch == frame);
        require(owner.retainsBorrowedResources() && !owner.complete && callbackCount == 0);
        owner.close(); require(!owner.wait.closed);
    }
    public static void main(String[] args) {
        testInvalid();
        testTerminal(new byte[0], false);
        testTerminal(new byte[] { 19, 37, 63 }, true);
        byte[] limit = new byte[Wire.MAX_BYTES];
        limit[0] = 7; limit[limit.length - 1] = 9;
        testTerminal(limit, false);
        testCopyFailure(false); testCopyFailure(true); testAllocationFailure(); testClosedDuringCopy();
        testUncertain(false); testUncertain(true); testTerminalFailure(false); testTerminalFailure(true);
        System.out.println("NETWORK_SCRATCH_CONTROL PASS exact-call-source;fake-boundaries;invalid;empty;limit;pending;terminal;copy-failure;cleanup-failure;allocation-failure;close-during-copy;uncertain-entry;uncertain-take;terminal-free-failure;callback-failure;COMPONENT_QUALIFICATION=pending");
    }
}

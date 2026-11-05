package dev.latent.guest;

import dev.latent.generated.Bindings;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicReference;
import org.teavm.interop.Address;

/** Real SDK wrappers on the JDK; no provider or component qualification. */
public final class NetworkBorrowControl {
    private static final class Network extends Resource {
        Network(int handle) { super(handle, -1, true); }
    }
    private static final class Original extends Resource {
        Original(int handle) { super(handle, -1); }
    }
    private static void require(boolean value) { if (!value) throw new AssertionError("network-borrow-control"); }
    private static void refused(Runnable action) {
        try { action.run(); throw new AssertionError("borrow-refusal-required"); }
        catch (IllegalStateException expected) { }
    }
    private static void invalid(Runnable action) {
        try { action.run(); throw new AssertionError("permit-refusal-required"); }
        catch (IllegalArgumentException expected) { }
    }
    @SuppressWarnings("unchecked")
    private static <T extends Throwable> void throwUnannounced(Throwable failure) throws T {
        throw (T) failure;
    }
    private static Wire.HostFunction failing(boolean retained) {
        return new Wire.HostFunction() {
            @Override public Address call(int operation, Address bytes, int length) {
                throw new IllegalStateException("controlled-failure");
            }
            @Override public boolean retainsBorrowedResources() { return retained; }
        };
    }
    // Reflection is used only by this JVM control to exercise the actual
    // generated class's private constructor. The public-API control separately
    // compiles an untrusted caller and requires that construction to fail.
    private static Wire.Writer writer(Wire.HostFunction function, int operation, int direction) throws Exception {
        var constructor = Bindings.BorrowPermit.class.getDeclaredConstructor(Wire.HostFunction.class, int.class, int.class);
        require(Modifier.isPrivate(constructor.getModifiers()));
        require(Bindings.BorrowPermit.class.getConstructors().length == 0);
        constructor.setAccessible(true);
        return new Wire.Writer(constructor.newInstance(function, operation, direction));
    }
    private static Object field(Object owner, String name) throws Exception {
        Field field = Wire.Writer.class.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(owner);
    }
    private static void threads() throws Exception {
        Network connection = new Network(19);
        CountDownLatch start = new CountDownLatch(1), held = new CountDownLatch(2), release = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Runnable read = () -> {
            try (Wire.Writer writer = writer(failing(false), 20, Wire.NETWORK_READ)) {
                start.await(); writer.resource(connection, false); held.countDown(); release.await();
            } catch (Throwable error) { failure.compareAndSet(null, error); held.countDown(); }
        };
        Runnable write = () -> {
            try (Wire.Writer writer = writer(failing(false), 21, Wire.NETWORK_WRITE)) {
                start.await(); writer.resource(connection, false); held.countDown(); release.await();
            } catch (Throwable error) { failure.compareAndSet(null, error); held.countDown(); }
        };
        Thread a = new Thread(read), b = new Thread(write);
        a.start(); b.start(); start.countDown(); held.await();
        try { require(failure.get() == null); refused(connection::consume); }
        finally { release.countDown(); a.join(); b.join(); }
        require(failure.get() == null && connection.consume() == 19);
    }
    public static void main(String[] args) throws Exception {
        Wire.HostFunction harmless = failing(false);
        Network connection = new Network(7);
        Wire.Writer read = writer(harmless, 1, Wire.NETWORK_READ);
        Wire.Writer write = writer(harmless, 2, Wire.NETWORK_WRITE);
        Wire.Writer ready = writer(harmless, 3, Wire.NETWORK_READY);
        Wire.Writer inspect = writer(null, 4, Wire.NETWORK_INSPECT);
        read.resource(connection, false);
        write.resource(connection, false);
        ready.resource(connection, false);
        inspect.resource(connection, false);
        // Every shutdown mode uses exclusive direction zero, so it cannot
        // overlap even read-only readiness or an outstanding read.
        try (Wire.Writer shutdown = writer(harmless, 5, 0)) {
            refused(() -> shutdown.resource(connection, false));
        }
        try (Wire.Writer duplicate = writer(harmless, 1, Wire.NETWORK_READ)) {
            refused(() -> duplicate.resource(connection, false));
        }
        refused(connection::consume);
        read.close();
        try (Wire.Writer nextRead = writer(harmless, 1, Wire.NETWORK_READ)) {
            nextRead.resource(connection, false);
            refused(connection::consume);
        }
        write.close(); ready.close();
        refused(connection::consume);
        try (Wire.Writer shutdown = writer(harmless, 5, 0)) {
            refused(() -> shutdown.resource(connection, false));
        }
        inspect.close(); inspect.close();
        try (Wire.Writer shutdown = writer(harmless, 5, 0);
             Wire.Writer blockedRead = writer(harmless, 1, Wire.NETWORK_READ)) {
            shutdown.resource(connection, false);
            refused(() -> blockedRead.resource(connection, false));
            refused(connection::consume);
        }
        require(connection.consume() == 7);
        refused(connection::borrow);

        Original original = new Original(9);
        try (Wire.Writer first = writer(harmless, 1, Wire.NETWORK_READ);
             Wire.Writer second = writer(harmless, 2, Wire.NETWORK_WRITE)) {
            first.resource(original, false);
            refused(() -> second.resource(original, false));
        }
        require(original.consume() == 9);

        Network uncertain = new Network(11);
        Wire.HostFunction inflight = failing(true);
        Wire.Writer held = writer(inflight, 1, Wire.NETWORK_READ);
        try (held) {
            held.resource(uncertain, false);
            held.bytes(new byte[] { 42, 71, 99 });
            refused(() -> held.call(inflight, 1, false));
        }
        // Inspect the real static root and its real input objects, rather than
        // relying on nondeterministic GC or a copied native representation.
        require(field(null, "rootedInputs") == held);
        require(((List<?>)field(held, "borrows")).contains(uncertain));
        byte[] retained = (byte[])field(held, "data");
        require(retained[8] == 42 && retained[9] == 71 && retained[10] == 99);
        refused(uncertain::consume);
        try (Wire.Writer duplicate = writer(harmless, 1, Wire.NETWORK_READ);
             Wire.Writer other = writer(harmless, 2, Wire.NETWORK_WRITE)) {
            refused(() -> duplicate.resource(uncertain, false));
            other.resource(uncertain, false);
        }
        refused(uncertain::consume);

        Network preEntry = new Network(13);
        try (Wire.Writer released = writer(harmless, 1, Wire.NETWORK_READ)) {
            released.resource(preEntry, false);
            refused(() -> released.call(harmless, 1, false));
        }
        require(preEntry.consume() == 13);
        require(field(null, "rootedInputs") == held);

        Network protectedResource = new Network(15);
        boolean[] delegated = {false};
        Wire.HostFunction forwarding = (operation, bytes, length) -> {
            delegated[0] = true;
            return harmless.call(operation + 1, bytes, length);
        };
        try (Wire.Writer checked = writer(harmless, 1, Wire.NETWORK_READ)) {
            checked.resource(protectedResource, false);
            invalid(() -> checked.call(forwarding, 1, false));
            invalid(() -> checked.call(harmless, 2, false));
            require(!delegated[0]);
        }
        try (Wire.Writer unpermitted = new Wire.Writer()) {
            unpermitted.resource(protectedResource, false);
            invalid(() -> unpermitted.call(forwarding, 1, false));
            require(!delegated[0]);
        }
        require(protectedResource.consume() == 15);

        Network reentrant = new Network(17);
        try (Wire.Writer writer = new Wire.Writer()) {
            Wire.HostFunction callback = (operation, bytes, length) -> {
                invalid(() -> writer.resource(reentrant, false));
                throw new IllegalStateException("controlled-failure");
            };
            refused(() -> writer.call(callback, 1, false));
        }
        require(reentrant.consume() == 17);
        // TeaVM's async continuation may rethrow an arbitrary Throwable even
        // where the source-level call declares no checked exception. Preserve
        // custody on that path just as for unchecked exceptional completion.
        Network checkedResource = new Network(21);
        Exception checkedFailure = new Exception("controlled-checked-failure");
        Wire.HostFunction checkedCall = new Wire.HostFunction() {
            @Override public Address call(int operation, Address bytes, int length) {
                NetworkBorrowControl.<RuntimeException>throwUnannounced(checkedFailure);
                throw new AssertionError("checked-failure-required");
            }
            @Override public boolean retainsBorrowedResources() { return true; }
        };
        Wire.Writer checkedWriter = writer(checkedCall, 6, Wire.NETWORK_READ);
        try (checkedWriter) {
            checkedWriter.resource(checkedResource, false);
            checkedWriter.bytes(new byte[] { 27, 39 });
            try { checkedWriter.call(checkedCall, 6, false); throw new AssertionError("checked-failure-required"); }
            catch (Exception actual) { require(actual == checkedFailure); }
        }
        require(field(null, "rootedInputs") == checkedWriter);
        require(((List<?>)field(checkedWriter, "borrows")).contains(checkedResource));
        byte[] checkedBytes = (byte[])field(checkedWriter, "data");
        require(checkedBytes[8] == 27 && checkedBytes[9] == 39);
        refused(checkedResource::consume);

        Network unknownResource = new Network(23);
        IllegalStateException originalFailure = new IllegalStateException("controlled-original-failure");
        Wire.HostFunction unknownCustody = new Wire.HostFunction() {
            @Override public Address call(int operation, Address bytes, int length) { throw originalFailure; }
            @Override public boolean retainsBorrowedResources() { throw new IllegalStateException("controlled-probe-failure"); }
        };
        Wire.Writer unknownWriter = writer(unknownCustody, 7, Wire.NETWORK_WRITE);
        try (unknownWriter) {
            unknownWriter.resource(unknownResource, false);
            unknownWriter.bytes(new byte[] { 51, 63 });
            try { unknownWriter.call(unknownCustody, 7, false); throw new AssertionError("original-failure-required"); }
            catch (IllegalStateException actual) { require(actual == originalFailure); }
        }
        require(field(null, "rootedInputs") == unknownWriter);
        require(((List<?>)field(unknownWriter, "borrows")).contains(unknownResource));
        byte[] unknownBytes = (byte[])field(unknownWriter, "data");
        require(unknownBytes[8] == 51 && unknownBytes[9] == 63);
        refused(unknownResource::consume);
        threads();
        System.out.println("NETWORK_BORROW_CONTROL PASS directions;duplicate;exclusive;shutdown;consume;uncertain;checked-throwable;unknown-custody;pre-entry;permit;delegation;rooted-inputs;COMPONENT_QUALIFICATION=pending");
    }
}

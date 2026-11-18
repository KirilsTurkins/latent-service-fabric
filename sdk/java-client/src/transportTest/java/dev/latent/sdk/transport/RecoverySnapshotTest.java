package dev.latent.sdk.transport;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import java.nio.ByteBuffer;
import java.util.AbstractList;
import java.util.Optional;

final class RecoverySnapshotTest {
    private static void check(boolean condition) { if (!condition) throw new AssertionError(); }
    private static TransactionClient.RecoveryIdentity identity(TransactionContext context) throws Exception {
        var field = TransactionContext.class.getDeclaredField("identity"); field.setAccessible(true);
        return (TransactionClient.RecoveryIdentity) field.get(context);
    }
    static void run() throws Exception {
        byte[] version = new byte[32], digest = new byte[32]; version[0] = 7; digest[0] = 9;
        var target = new Transactions.GetEffectRequest(Optional.empty(), Optional.empty(), "effect", Optional.empty());
        var mutation = new Transactions.PlanEffectMutationRequest(Optional.of(target), "operation",
                Transactions.StateMutationKind.RETRY_KNOWN_FAILED_EFFECT, ByteBuffer.wrap(version),
                "sha256:" + "a".repeat(64), "retry", 1);
        var plan = new Transactions.EffectManagementPlan(Optional.of(mutation), ByteBuffer.wrap(digest),
                1, 1, 1, 1, 2000, 1000, Transactions.EffectDisposition.KNOWN_FAILURE,
                Transactions.EffectPlanSafety.KNOWN_NONEXECUTION, Optional.empty());
        var context = new TransactionContext();
        context.capture(new Transactions.GetStateOperationReceiptRequest(Optional.empty(), "operation", Optional.of(plan)));
        var saved = identity(context);
        version[0] = 1; digest[0] = 2;
        check(saved.effectMutation().orElseThrow().expectedVersion().get(0) == 7);
        check(saved.effectPlan().orElseThrow().planDigest().get(0) == 9);
        check(saved.expectedVersion().orElseThrow().get(0) == 7);
        var large = new AbstractList<Transactions.ExpectedVersion>() {
            @Override public int size() { return 129; }
            @Override public Transactions.ExpectedVersion get(int index) { throw new AssertionError("unbounded iteration"); }
        };
        context.capture(new Transactions.InvokeCommandRequest(Optional.empty(), Optional.empty(), Optional.empty(), "format", large, Optional.empty()));
        check(identity(context).expectedVersions().isEmpty());
        var misleading = new AbstractList<Integer>() {
            @Override public int size() { return 1; }
            @Override public Integer get(int index) { return index; }
            @Override public java.util.Iterator<Integer> iterator() {
                return java.util.stream.IntStream.range(0, 129).boxed().iterator();
            }
        };
        try { TransactionProtocol.list(misleading, 128); throw new AssertionError("accepted misleading list"); }
        catch (Protocol.Invalid expected) { /* iteration stays within the declared bound */ }
        var expectedVersion = new Transactions.ExpectedVersion(ByteBuffer.wrap(new byte[] { 1 }), Optional.empty(), Optional.of(ByteBuffer.wrap(new byte[] { 2 })));
        var misleadingVersions = new AbstractList<Transactions.ExpectedVersion>() {
            @Override public int size() { return 1; }
            @Override public Transactions.ExpectedVersion get(int index) { return expectedVersion; }
            @Override public java.util.Iterator<Transactions.ExpectedVersion> iterator() {
                return java.util.Collections.nCopies(129, expectedVersion).iterator();
            }
        };
        try {
            TransactionWire.toWire(new Transactions.InvokeCommandRequest(Optional.empty(), Optional.empty(), Optional.empty(), "format", misleadingVersions, Optional.empty()));
            throw new AssertionError("unbounded generated encoder");
        } catch (Protocol.Invalid expected) { /* the encoder enforces its own list bound */ }
        var misleadingMap = new java.util.AbstractMap<String, String>() {
            @Override public java.util.Set<Entry<String, String>> entrySet() {
                return new java.util.AbstractSet<>() {
                    @Override public int size() { return 1; }
                    @Override public java.util.Iterator<Entry<String, String>> iterator() {
                        return java.util.stream.IntStream.range(0, 33)
                                .mapToObj(i -> (Entry<String, String>) new SimpleImmutableEntry<>("key" + i, "value"))
                                .iterator();
                    }
                };
            }
        };
        var metadata = TransactionProtocol.class.getDeclaredMethod("metadata", Object.class, boolean.class);
        metadata.setAccessible(true);
        try { metadata.invoke(null, misleadingMap, true); throw new AssertionError("accepted misleading map"); }
        catch (java.lang.reflect.InvocationTargetException expected) { check(expected.getCause() instanceof Protocol.Invalid); }
    }
    public static void main(String[] args) throws Exception { run(); System.out.println("Java recovery snapshots passed"); }
}

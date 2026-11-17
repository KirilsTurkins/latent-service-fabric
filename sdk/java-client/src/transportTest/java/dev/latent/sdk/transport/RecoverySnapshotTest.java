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
    }
    public static void main(String[] args) throws Exception { run(); System.out.println("Java recovery snapshots passed"); }
}

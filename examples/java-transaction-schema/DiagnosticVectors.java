package dev.latent.app;

/** JVM helper semantics only; this does not establish host transaction behavior. */
public final class DiagnosticVectors {
    public static void main(String[] arguments) {
        if (arguments.length != 1) throw new IllegalArgumentException("diagnostic-vector-required");
        TransactionDiagnostics.enter();
        if (arguments[0].equals("ordinary")) {
            if (TransactionDiagnostics.businessDelta(7) != 7) throw new AssertionError("ordinary-delta");
            TransactionDiagnostics.afterStage(7);
        } else if (arguments[0].equals("trap")) {
            if (TransactionDiagnostics.businessDelta(TransactionDiagnostics.TRAP_DELTA) != 1
                || TransactionDiagnostics.businessDelta(TransactionDiagnostics.LOOP_DELTA) != 1)
                throw new AssertionError("bounded-diagnostic-delta");
            expect("diagnostic-trap-after-stage", () -> TransactionDiagnostics.afterStage(TransactionDiagnostics.TRAP_DELTA));
        } else if (arguments[0].equals("reused")) {
            expect("diagnostic-instance-reused", TransactionDiagnostics::enter);
        } else {
            throw new IllegalArgumentException("unknown-diagnostic-vector");
        }
        System.out.println("passed:" + arguments[0]);
    }

    private static void expect(String reason, Runnable operation) {
        try {
            operation.run();
            throw new AssertionError("diagnostic-failure-missing");
        } catch (IllegalStateException error) {
            if (!reason.equals(error.getMessage())) throw new AssertionError("diagnostic-reason");
        }
    }
}

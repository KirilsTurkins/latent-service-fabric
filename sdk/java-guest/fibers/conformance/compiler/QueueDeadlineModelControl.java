package dev.latent.guest.runtime.compiler;

import java.lang.reflect.InvocationTargetException;
import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.BinaryInstruction;
import org.teavm.model.instructions.BinaryOperation;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.NumericOperandType;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Mutations of the actual pinned queue IR, not an application queue substitute. */
public final class QueueDeadlineModelControl {
    private static final MethodDescriptor PUMP = new MethodDescriptor("processSingle", ValueType.LONG);
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static Program pump(ClassHolder cls) { return cls.getMethod(PUMP).getProgram(); }
    private static InvokeInstruction clock(Program program, int index) {
        int seen = 0;
        for (var block : program.getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call
                    && call.getMethod().equals(new MethodReference("java.lang.System", "currentTimeMillis", ValueType.LONG))) {
                if (seen++ == index) return call;
            }
        }
        throw new AssertionError("actual-queue-clock");
    }
    private static void verify(Program program, boolean rejected) throws Exception {
        var method = RuntimePlugin.class.getDeclaredMethod("verifyQueueClock", Program.class);
        method.setAccessible(true);
        try {
            method.invoke(null, program);
            require(!rejected, "unreviewed-queue-rejected");
        } catch (InvocationTargetException error) {
            require(rejected && error.getCause() instanceof IllegalStateException, "actual-queue-shape-failure");
        }
    }
    public static void main(String[] arguments) throws Exception {
        var loader = QueueDeadlineModelControl.class.getClassLoader();
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var original = source.get("org.teavm.runtime.EventQueue");
        require(original != null && pump(original) != null, "actual-locked-queue-class");
        verify(pump(original), false);

        var missing = ModelUtils.copyClass(original);
        clock(pump(missing), 1).setMethod(new MethodReference("java.lang.System", "nanoTime", ValueType.LONG));
        verify(pump(missing), true);

        var wrongDelay = ModelUtils.copyClass(original);
        var second = clock(pump(wrongDelay), 1).getReceiver();
        boolean changed = false;
        for (var block : pump(wrongDelay).getBasicBlocks()) for (var instruction : block) {
            if (!changed && instruction instanceof BinaryInstruction binary
                    && binary.getOperation() == BinaryOperation.SUBTRACT
                    && binary.getOperandType() == NumericOperandType.LONG) {
                binary.setSecondOperand(second); changed = true;
            }
        }
        require(changed, "actual-queue-delay-mutated");
        verify(pump(wrongDelay), true);

        var wrongComparison = ModelUtils.copyClass(original);
        var first = clock(pump(wrongComparison), 0).getReceiver();
        changed = false;
        for (var block : pump(wrongComparison).getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof BinaryInstruction binary
                    && binary.getOperandType() == NumericOperandType.LONG
                    && (binary.getOperation() == BinaryOperation.COMPARE_GREATER || binary.getOperation() == BinaryOperation.COMPARE_LESS)) {
                binary.setSecondOperand(first); changed = true;
            }
        }
        require(changed, "actual-queue-comparison-mutated");
        verify(pump(wrongComparison), true);

        var transformed = ModelUtils.copyClass(original);
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class, ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        transform.invoke(new RuntimePlugin(), transformed, null);
        int hooks = 0;
        for (var block : pump(transformed).getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call
                    && call.getMethod().equals(new MethodReference("dev.latent.guest.runtime.Activation", "queueMonotonicMillis", ValueType.LONG))) hooks++;
        }
        require(hooks == 2, "both-queue-samples-use-owned-first-latch");
        verify(pump(transformed), true);
        System.out.println("QUEUE_DEADLINE_MODEL_CONTROL PASS actual-locked-queue;first-sample-delays;second-sample-comparison;owned-clock-hooks=2;negative-shapes=4");
    }
}

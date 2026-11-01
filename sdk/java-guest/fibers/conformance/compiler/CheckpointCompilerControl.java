package org.teavm.dependency;

import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.interop.Unmanaged;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ElementModifier;
import org.teavm.model.ListableClassReaderSource;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.EmptyInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.vm.TeaVMBuilder;
import org.teavm.vm.TeaVMOptimizationLevel;

/** Real bytecode/JCL/C-frontend control; never executes the fixture initializers. */
public final class CheckpointCompilerControl {
    private static final String REFUSAL = "java-checkpoint-nonsuspendable-progress-741";

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static final class AnalysisComplete extends RuntimeException {
        private AnalysisComplete() {
            super(null, null, false, false);
        }
    }

    private static final class ProbeTarget extends CTarget {
        boolean analyzed;

        ProbeTarget() {
            super(new CNameProvider());
            setMinHeapSize(1024 * 1024);
            setMaxHeapSize(4 * 1024 * 1024);
        }

        @Override
        public void analyzeBeforeOptimizations(ListableClassReaderSource source) {
            // Invoke the real owner after dependency completion and normal
            // JCL/C transformations. Do not substitute a synthetic call graph.
            super.analyzeBeforeOptimizations(source);
            analyzed = true;
            throw new AnalysisComplete();
        }
    }

    public static final class Finite {
        private static final int[] VALUES = new int[256];
        private static int result;
        static {
            for (int index = 0; index < VALUES.length; ++index) VALUES[index] = index;
        }
        public static void main(String[] arguments) {
            result = VALUES[arguments.length & 255];
        }
    }

    public static final class InitializerPolling {
        private static volatile boolean ready;
        static {
            while (!ready) {
                // No checkpoint call and no finite induction argument.
            }
        }
        public static void main(String[] arguments) {
            ready = arguments.length != 0;
        }
    }

    public static final class UnmanagedPolling {
        private static volatile boolean ready;
        @Unmanaged
        private static void poll() {
            while (!ready) {
                // A loop-free caller does not make its unmanaged callee finite.
            }
        }
        public static void main(String[] arguments) {
            poll();
        }
    }

    public static final class ManagedPolling {
        private static volatile boolean ready;
        public static void main(String[] arguments) {
            while (!ready) {
                // This checks exclusion, not managed runtime fairness.
            }
        }
    }

    public static final class RecursiveInitializer {
        private static int result = recurse(0);
        private static int recurse(int value) {
            return recurse(value + 1);
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class FiniteUnmanaged {
        private static int result;
        @Unmanaged
        private static int sum(int limit) {
            int total = 0;
            for (int index = 0; index < limit; ++index) total += index;
            return total;
        }
        public static void main(String[] arguments) {
            result = sum(arguments.length);
        }
    }

    public static final class NestedCounted {
        private static int result;
        static {
            for (int outer = 0; outer < 4; ++outer) {
                for (int inner = 0; inner < 3; ++inner) result += outer + inner;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ChangingBound {
        private static volatile int limit = 3;
        private static int result;
        static {
            // The signed induction rank decreases even when the bound changes.
            for (int index = 0; index < limit; ++index) {
                limit = (index & 1) + 4;
                result = index;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class WrappingCounted {
        private static volatile int limit = Integer.MAX_VALUE;
        private static int result;
        static {
            // A non-strict test admits MAX_VALUE and lets the increment wrap.
            for (int index = Integer.MAX_VALUE; index <= limit; ++index) result = index;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ResetCounted {
        private static volatile int limit = 4;
        private static int result;
        static {
            for (int index = 0; index < limit; ++index) {
                result = index;
                index = 0;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class ExceptionalRetry {
        private static volatile int divisor;
        private static int result;
        static {
            for (int index = 0; index < 3;) {
                try {
                    result = 1 / divisor;
                    ++index;
                } catch (ArithmeticException retry) {
                    // The exceptional backedge bypasses the induction update.
                }
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    @Unmanaged
    public static final class UnmanagedClassPolling {
        private static volatile boolean ready;
        private static void poll() {
            while (!ready) { }
        }
        public static void main(String[] arguments) {
            poll();
        }
    }

    public static final class TransitiveInitializer {
        private static volatile boolean ready;
        private static int result = first();
        private static int first() {
            return second();
        }
        private static int second() {
            while (!ready) { }
            return 1;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class NearMaxCounted {
        private static int result;
        static {
            for (int index = Integer.MAX_VALUE - 2; index < Integer.MAX_VALUE; ++index) result = index;
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class NestedPolling {
        private static volatile boolean ready;
        private static int result;
        static {
            for (int index = 0; index < 3; ++index) {
                while (!ready) { }
                result = index;
            }
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class MutualRecursion {
        private static int result = first(0);
        private static int first(int value) {
            return second(value + 1);
        }
        private static int second(int value) {
            return first(value + 1);
        }
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    public static final class VirtualInitializer {
        private interface Supplier {
            int get();
        }
        private static final class PollingSupplier implements Supplier {
            private static volatile boolean ready;
            public int get() {
                while (!ready) { }
                return 1;
            }
        }
        private static int read(Supplier supplier) {
            return supplier.get();
        }
        private static int result = read(new PollingSupplier());
        public static void main(String[] arguments) {
            result += arguments.length;
        }
    }

    private static void loop(MethodHolder method) {
        Program program = new Program();
        for (int index = 0; index <= method.parameterCount(); ++index) program.createVariable();
        var block = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        block.add(jump);
        method.setProgram(program);
    }

    private static boolean mutate(ClassHolder cls, String mutation) {
        if (mutation.equals("runtime-initializer") && cls.getName().equals("org.teavm.runtime.Allocator")) {
            var descriptor = new MethodDescriptor("<clinit>", ValueType.VOID);
            require(cls.getMethod(descriptor) == null, "checkpoint-control-original-initializer-absent");
            var method = new MethodHolder(descriptor);
            method.getModifiers().add(ElementModifier.STATIC);
            loop(method);
            cls.addMethod(method);
            return true;
        }
        if (mutation.equals("class-object-helper") && cls.getName().equals("java.lang.Class")) {
            var method = cls.getMethod(new MethodDescriptor("createClass",
                    ValueType.object("org.teavm.runtime.reflect.ClassInfo"), ValueType.object("java.lang.Class")));
            require(method != null, "checkpoint-control-class-object-helper-present");
            loop(method);
            return true;
        }
        if (mutation.equals("string-copy-body") && cls.getName().equals("java.lang.String")) {
            var method = cls.getMethod(new MethodDescriptor("<init>", ValueType.arrayOf(ValueType.CHARACTER),
                    ValueType.VOID));
            require(method != null && method.getProgram() != null, "checkpoint-control-string-copy-body-present");
            method.getProgram().basicBlockAt(0).getFirstInstruction().insertPrevious(new EmptyInstruction());
            return true;
        }
        return false;
    }

    private static void check(String entry, boolean corrected, boolean unsafe, String mutation) {
        var target = new ProbeTarget();
        var references = new ReferenceCache();
        var builder = new TeaVMBuilder(target).setReferenceCache(references);
        // The split-loader control supplies the same explicit application loader
        // boundary as the production in-process Gradle build strategy.
        var loader = Thread.currentThread().getContextClassLoader();
        builder.setClassLoader(loader).setResourceProvider(new ClasspathResourceProvider(loader));
        // Match TeaVMTool's maintained non-incremental input preparation.
        builder.setClassSource(new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                builder.getResourceProvider(), references, builder.getClassLoader())));
        var vm = builder.build();
        vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);
        vm.installPlugins();
        boolean[] changed = { false };
        vm.add((ClassHolder cls, ClassHolderTransformerContext context) -> {
            changed[0] |= mutate(cls, mutation);
        });
        vm.setEntryPoint(entry);
        boolean refused = false;
        try {
            vm.build(name -> {
                throw new AssertionError("checkpoint-control-must-not-generate-code");
            }, "unused.c");
            throw new AssertionError("checkpoint-control-must-reach-owning-finder");
        } catch (AnalysisComplete completed) {
            require(target.analyzed, "checkpoint-control-real-c-analysis-completed");
        } catch (IllegalStateException failure) {
            if (!(corrected && unsafe && REFUSAL.equals(failure.getMessage()))) {
                throw new AssertionError("checkpoint-control-unexpected-compiler-refusal", failure);
            }
            refused = true;
        }
        require(mutation.isEmpty() || changed[0], "checkpoint-control-mutation-was-applied");
        require(vm.getProblemProvider().getSevereProblems().isEmpty(),
                "checkpoint-control-no-hidden-compiler-errors");
        require(refused == (corrected && unsafe), "checkpoint-control-progress-verdict");
    }

    public static void checkClasslibIdentity(String mode) {
        require(mode.equals("original") || mode.equals("corrected"), "checkpoint-classlib-control-mode");
        // A changed archive retains all class bytes but is not the locked proof
        // source. Only the corrected finder must refuse its finite initializer.
        check(Finite.class.getName(), mode.equals("corrected"), true, "");
    }

    public static void main(String[] arguments) {
        require(arguments.length == 1 && (arguments[0].equals("original")
                || arguments[0].equals("corrected")), "checkpoint-compiler-control-mode");
        boolean corrected = arguments[0].equals("corrected");
        check(Finite.class.getName(), corrected, false, "");
        check(InitializerPolling.class.getName(), corrected, true, "");
        check(UnmanagedPolling.class.getName(), corrected, true, "");
        check(ManagedPolling.class.getName(), corrected, false, "");
        check(RecursiveInitializer.class.getName(), corrected, true, "");
        for (String mutation : new String[] { "runtime-initializer", "class-object-helper", "string-copy-body" }) {
            check(Finite.class.getName(), corrected, true, mutation);
        }
        check(FiniteUnmanaged.class.getName(), corrected, false, "");
        check(NestedCounted.class.getName(), corrected, false, "");
        check(ChangingBound.class.getName(), corrected, false, "");
        check(WrappingCounted.class.getName(), corrected, true, "");
        check(ResetCounted.class.getName(), corrected, true, "");
        check(ExceptionalRetry.class.getName(), corrected, true, "");
        check(UnmanagedClassPolling.class.getName(), corrected, true, "");
        check(TransitiveInitializer.class.getName(), corrected, true, "");
        check(NearMaxCounted.class.getName(), corrected, false, "");
        check(NestedPolling.class.getName(), corrected, true, "");
        check(MutualRecursion.class.getName(), corrected, true, "");
        check(VirtualInitializer.class.getName(), corrected, true, "");
        System.out.println("CHECKPOINT_COMPILER_CONTROL PASS " + arguments[0]
                + ";finite;initializer;unmanaged;managed;recursion;runtime-initializer;class-object-helper;string-copy-body;finite-unmanaged;nested-counted;changing-bound;wrapping-counted;reset-counted;exceptional-retry;unmanaged-class;transitive-initializer;near-max-counted;nested-polling;mutual-recursion;virtual-initializer");
    }
}

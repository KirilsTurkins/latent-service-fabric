package org.teavm.dependency;

import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.interop.Unmanaged;
import org.teavm.model.ListableClassReaderSource;
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
            // Exercise the real owning call, after dependency completion and
            // normal JCL/C transformations. Do not substitute a synthetic graph.
            super.analyzeBeforeOptimizations(source);
            analyzed = true;
            throw new AnalysisComplete();
        }
    }

    public static final class Finite {
        private static final int[] VALUES = new int[256];
        private static int result;
        static {
            for (int index = 0; index < VALUES.length; ++index) {
                VALUES[index] = index;
            }
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
                // This control checks exclusion, not managed runtime fairness.
            }
        }
    }

    private static void check(String entry, boolean corrected, boolean unsafe) {
        var target = new ProbeTarget();
        var vm = new TeaVMBuilder(target).build();
        vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);
        vm.installPlugins();
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
            require(corrected && unsafe && REFUSAL.equals(failure.getMessage()),
                    "checkpoint-control-unexpected-compiler-refusal");
            refused = true;
        }
        require(vm.getProblemProvider().getSevereProblems().isEmpty(),
                "checkpoint-control-no-hidden-compiler-errors");
        require(refused == (corrected && unsafe), "checkpoint-control-progress-verdict");
    }

    public static void main(String[] arguments) {
        require(arguments.length == 1 && (arguments[0].equals("original")
                || arguments[0].equals("corrected")), "checkpoint-compiler-control-mode");
        boolean corrected = arguments[0].equals("corrected");
        check(Finite.class.getName(), corrected, false);
        check(InitializerPolling.class.getName(), corrected, true);
        check(UnmanagedPolling.class.getName(), corrected, true);
        check(ManagedPolling.class.getName(), corrected, false);
        System.out.println("CHECKPOINT_COMPILER_CONTROL PASS " + arguments[0]
                + ";finite;initializer;unmanaged;managed");
    }
}

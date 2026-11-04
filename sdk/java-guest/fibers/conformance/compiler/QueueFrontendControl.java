package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.ReferenceCache;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;
import org.teavm.vm.MemoryBuildTarget;
import org.teavm.vm.TeaVMBuilder;
import org.teavm.vm.TeaVMOptimizationLevel;

/** Locked C-frontend control only: no component or native host is executed. */
public final class QueueFrontendControl {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    public static void main(String[] args) throws Exception {
        ClassLoader loader = QueueFrontendControl.class.getClassLoader();
        var mapping = DefaultSubstituteClassNameMapping.createWithPolicies(
                List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution()));
        var source = new PreOptimizingClassHolderSource(
                new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(), mapping));
        var vm = new TeaVMBuilder(new CTarget(new CNameProvider())).setClassSource(source)
                .setClassLoader(loader).setStrict(true).build();
        int[] seen = { 0 };
        vm.add((cls, context) -> {
            if (cls.getName().equals("org.teavm.runtime.EventQueue")) seen[0]++;
            EventQueueHeapMethods.transform(cls, context);
        });
        vm.installPlugins();
        vm.setEntryPoint(App.class.getName());
        vm.setOptimizationLevel(TeaVMOptimizationLevel.SIMPLE);
        var output = new MemoryBuildTarget();
        vm.build(output, "queue-frontend");
        require(seen[0] == 1, "queue-heap-frontend-transform-count");
        require(vm.getProblemProvider().getProblems().isEmpty(), "queue-heap-frontend-problems");
        require(!output.getNames().isEmpty() && output.getNames().size() <= 1024, "queue-heap-frontend-output");
        long bytes = 0;
        for (String name : output.getNames()) {
            bytes += output.getContent(name).length;
            require(bytes <= 16 * 1024 * 1024, "queue-heap-frontend-output-bound");
        }
        require(bytes > 0, "queue-heap-frontend-output-empty");
        System.out.println("QUEUE_FRONTEND_CONTROL PASS actual-locked-c-emission;event-queue-transform-once");
    }

    public static final class App {
        public static void main(String[] args) {
            new Thread(() -> { }).start();
        }
    }
}

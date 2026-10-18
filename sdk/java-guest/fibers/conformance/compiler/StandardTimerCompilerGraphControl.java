package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.backend.c.CTarget;
import org.teavm.backend.c.generate.CNameProvider;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;
import org.teavm.vm.*;

/** The actual locked dependency analyzer and C emitter must retain accepted work. */
public final class StandardTimerCompilerGraphControl {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    static void run() throws Exception {
        ClassLoader loader = StandardTimerCompilerGraphControl.class.getClassLoader();
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        var vm = new TeaVMBuilder(new CTarget(new CNameProvider())).setClassSource(source)
            .setClassLoader(loader).setStrict(true).build();
        vm.installPlugins();
        var normalize = RuntimePlugin.class.getDeclaredMethod("normalizeOwnedTimerReferences", ClassHolder.class);
        normalize.setAccessible(true);
        // Isolate the same timer replacement and identity normalization. The
        // private host ledger is not the activation runtime or guest bindings.
        vm.add((cls, context) -> {
            StandardTimerMethods.transform(cls, context);
            try { normalize.invoke(null, cls); }
            catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
        });
        vm.setEntryPoint(App.class.getName());
        vm.setOptimizationLevel(TeaVMOptimizationLevel.SIMPLE);
        var output = new MemoryBuildTarget();
        vm.build(output, "timer-graph");
        require(vm.getProblemProvider().getProblems().isEmpty(), "actual-timer-compiler-problems");
        for (String cls : List.of("java.util.Timer", "dev.latent.guest.runtime.util.Timer$Worker", App.class.getName() + "$1")) {
            String method = cls.equals("java.util.Timer") ? "work" : "run";
            require(vm.getMethods().contains(new MethodReference(cls, method, ValueType.VOID)),
                "actual-timer-worker-and-callback-reachable:" + cls);
        }
        require(!output.getNames().isEmpty() && output.getNames().size() <= 1024, "bounded-timer-C-emission");
        long bytes = 0;
        for (String name : output.getNames()) bytes += output.getContent(name).length;
        require(bytes > 0 && bytes <= 16 * 1024 * 1024, "bounded-timer-C-emission-bytes");
    }

    public static final class App {
        public static void main(String[] args) {
            var timer = new java.util.Timer("compiler-graph", true);
            timer.schedule(new java.util.TimerTask() { @Override public void run() { } }, 0);
            timer.cancel();
        }
    }
}

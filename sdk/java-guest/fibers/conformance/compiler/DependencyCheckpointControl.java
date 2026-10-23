package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.common.LoopGraph;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Real maintained plugin and unchanged dependency IR; no application initialization. */
public final class DependencyCheckpointControl {
    private static final String LIBRARY = "org.apache.commons.lang3.concurrent.AtomicSafeInitializer";
    private static final MethodDescriptor GET = new MethodDescriptor("get", ValueType.object("java.lang.Object"));

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static int checkpoints(MethodHolder method) {
        int count = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call
                    && call.getMethod().equals(new MethodReference("dev.latent.guest.runtime.Activation",
                        "checkpoint", ValueType.VOID))) count++;
        }
        return count;
    }

    private static Set<Integer> headers(Program program) {
        var graph = new LoopGraph(ProgramUtils.buildControlFlowGraph(program));
        var result = new HashSet<Integer>();
        for (int index = 0; index < graph.size(); index++) {
            var loop = graph.loopAt(index);
            if (loop != null) result.add(loop.getHead());
        }
        return result;
    }

    private static RuntimePlugin plugin(String selected) throws Exception {
        var plugin = new RuntimePlugin();
        var field = RuntimePlugin.class.getDeclaredField("applicationClasses");
        field.setAccessible(true);
        @SuppressWarnings("unchecked") var classes = (Set<String>)field.get(plugin);
        if (selected != null) classes.add(selected);
        return plugin;
    }

    private static void transform(RuntimePlugin plugin, ClassHolder cls) throws Exception {
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class,
            ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        transform.invoke(plugin, cls, null);
    }

    private static MethodHolder loop(String name) {
        var method = new MethodHolder(name, ValueType.VOID);
        method.getModifiers().add(ElementModifier.STATIC);
        var program = new Program();
        program.createVariable();
        var block = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        block.add(jump);
        method.setProgram(program);
        return method;
    }

    public static void main(String[] arguments) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            DependencyCheckpointControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var original = source.get(LIBRARY);
        require(original != null && original.getMethod(GET) != null, "exact-published-library-method");
        var originalGet = original.getMethod(GET);
        var heads = headers(originalGet.getProgram());
        require(!heads.isEmpty() && checkpoints(originalGet) == 0, "real-uninstrumented-dependency-loop");
        var selected = ModelUtils.copyClass(original);
        var get = selected.getMethod(GET);
        var program = get.getProgram();
        var originalInstructions = new java.util.ArrayList<Instruction>();
        for (var block : program.getBasicBlocks()) for (var instruction : block) originalInstructions.add(instruction);
        transform(plugin(LIBRARY), selected);
        require(get.getProgram() == program && checkpoints(get) == heads.size(), "same-real-program-with-loop-checkpoints");
        var remaining = new java.util.ArrayList<Instruction>();
        for (var block : program.getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call && call.getMethod().getClassName()
                    .equals("dev.latent.guest.runtime.Activation")) continue;
            remaining.add(instruction);
        }
        require(originalInstructions.equals(remaining), "all-original-dependency-instructions-retained");
        for (int head : heads) {
            var first = program.basicBlockAt(head).getFirstInstruction();
            require(first instanceof InvokeInstruction && ((InvokeInstruction)first).getMethod().equals(
                new MethodReference("dev.latent.guest.runtime.Activation", "checkpoint", ValueType.VOID)),
                "checkpoint-at-real-loop-header");
        }
        var unselected = ModelUtils.copyClass(original);
        transform(plugin(null), unselected);
        require(checkpoints(unselected.getMethod(GET)) == 0, "unselected-class-unchanged");
        var nonSuspendable = new ClassHolder("qualification.NonSuspendable");
        var initializer = loop("<clinit>");
        var unmanaged = loop("unmanaged");
        unmanaged.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
        nonSuspendable.addMethod(initializer);
        nonSuspendable.addMethod(unmanaged);
        transform(plugin(nonSuspendable.getName()), nonSuspendable);
        require(checkpoints(initializer) == 0 && checkpoints(unmanaged) == 0, "non-suspendable-regions-unchanged");
        require(checkpoints(originalGet) == 0, "original-library-model-unchanged");
        System.out.println("DEPENDENCY_CHECKPOINT_CONTROL PASS actual-published-loop;original-instructions;unselected-negative;class-initializer-unmanaged-negatives");
    }
}

package dev.latent.guest.runtime.compiler;

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

/** Actual RuntimePlugin on the failing self-edge and real Java IR; no guest execution. */
public final class SelfLoopCheckpointControl {
    private static final MethodReference CHECKPOINT = new MethodReference(
            "dev.latent.guest.runtime.Activation", "checkpoint", ValueType.VOID);
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
    private static RuntimePlugin plugin(String selected) throws Exception {
        var plugin = new RuntimePlugin();
        var field = RuntimePlugin.class.getDeclaredField("applicationClasses");
        field.setAccessible(true);
        @SuppressWarnings("unchecked") var classes = (Set<String>) field.get(plugin);
        if (selected != null) classes.add(selected);
        return plugin;
    }
    private static void transform(RuntimePlugin plugin, ClassHolder cls) throws Exception {
        var method = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class,
                ClassHolderTransformerContext.class);
        method.setAccessible(true);
        method.invoke(plugin, cls, null);
    }
    private static int checkpoints(MethodHolder method) {
        int count = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block)
            if (instruction instanceof InvokeInstruction call && call.getMethod().equals(CHECKPOINT)) count++;
        return count;
    }
    // Exact control shape that exposed the missing checkpoint in #1643.
    private static MethodHolder selfLoop(String name) {
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
    private static MethodHolder unreachableSelfLoop() {
        var method = new MethodHolder("unreachable", ValueType.VOID);
        method.getModifiers().add(ElementModifier.STATIC);
        var program = new Program(); program.createVariable();
        var entry = program.createBasicBlock(); entry.add(new ExitInstruction());
        var dead = program.createBasicBlock();
        var jump = new JumpInstruction(); jump.setTarget(dead); dead.add(jump);
        method.setProgram(program);
        return method;
    }
    private static MethodHolder overlappingLoopHeaders() {
        var method = new MethodHolder("overlap", ValueType.VOID);
        method.getModifiers().add(ElementModifier.STATIC);
        var program = new Program(); program.createVariable(); var condition = program.createVariable();
        var entry = program.createBasicBlock(); var head = program.createBasicBlock(); var body = program.createBasicBlock();
        var constant = new IntegerConstantInstruction(); constant.setReceiver(condition); constant.setConstant(1); entry.add(constant);
        var enter = new JumpInstruction(); enter.setTarget(head); entry.add(enter);
        var branch = new BranchingInstruction(BranchingCondition.NOT_EQUAL);
        branch.setOperand(condition); branch.setConsequent(head); branch.setAlternative(body); head.add(branch);
        var back = new JumpInstruction(); back.setTarget(head); body.add(back);
        method.setProgram(program);
        return method;
    }
    public static final class RealSpin {
        private static volatile boolean ready;
        public static void spin() { while (!ready) { } }
    }
    public static void main(String[] arguments) throws Exception {
        var selected = new ClassHolder("qualification.NetworkBorrowSelectedLoop");
        var single = selfLoop("run");
        var originalJump = single.getProgram().basicBlockAt(0).getFirstInstruction();
        var graph = ProgramUtils.buildControlFlowGraph(single.getProgram());
        var oldLoops = new LoopGraph(graph);
        require(graph.outgoingEdges(0).length == 1 && graph.outgoingEdges(0)[0] == 0
                && oldLoops.loopAt(0) == null, "single-block-reproduces-pinned-loopgraph-gap");
        selected.addMethod(single);
        var dead = unreachableSelfLoop(); selected.addMethod(dead);
        var overlap = overlappingLoopHeaders(); selected.addMethod(overlap);
        transform(plugin(selected.getName()), selected);
        require(checkpoints(single) == 1 && single.getProgram().basicBlockAt(0).getFirstInstruction()
                instanceof InvokeInstruction && originalJump.getPrevious() != null,
                "selected-self-loop-checkpoint");
        require(checkpoints(dead) == 0, "unreachable-self-loop-unchanged");
        require(checkpoints(overlap) == 1 && overlap.getProgram().basicBlockAt(1).getFirstInstruction()
                instanceof InvokeInstruction, "overlapping-loop-header-deduplicated");
        var unselected = new ClassHolder("qualification.UnselectedSelfLoop");
        var untouched = selfLoop("run"); unselected.addMethod(untouched);
        transform(plugin(null), unselected);
        require(checkpoints(untouched) == 0, "unselected-self-loop-unchanged");
        var excluded = new ClassHolder("qualification.ExcludedSelfLoop");
        var initializer = selfLoop("<clinit>"); var unmanaged = selfLoop("unmanaged");
        unmanaged.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
        excluded.addMethod(initializer); excluded.addMethod(unmanaged);
        transform(plugin(excluded.getName()), excluded);
        require(checkpoints(initializer) == 0 && checkpoints(unmanaged) == 0, "excluded-methods-unchanged");
        var excludedClass = new ClassHolder("qualification.ExcludedClassSelfLoop");
        excludedClass.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
        var classMethod = selfLoop("run"); excludedClass.addMethod(classMethod);
        transform(plugin(excludedClass.getName()), excludedClass);
        require(checkpoints(classMethod) == 0, "excluded-class-unchanged");
        var source = new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(
                new ClasspathResourceProvider(SelfLoopCheckpointControl.class.getClassLoader()), new ReferenceCache(),
                DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy()))));
        var actual = source.get(RealSpin.class.getName());
        require(actual != null, "real-java-class");
        var copy = ModelUtils.copyClass(actual);
        var spin = copy.getMethod(new MethodDescriptor("spin", ValueType.VOID));
        require(spin != null && spin.getProgram() != null && checkpoints(spin) == 0, "real-java-original-loop");
        var actualGraph = ProgramUtils.buildControlFlowGraph(spin.getProgram());
        var actualLoops = new LoopGraph(actualGraph);
        boolean missedSelfEdge = false;
        for (int index = 0; index < actualGraph.size(); index++) {
            if (actualLoops.indexAt(index) < 0 || actualLoops.loopAt(index) != null) continue;
            for (int successor : actualGraph.outgoingEdges(index))
                if (successor == index) missedSelfEdge = true;
        }
        transform(plugin(copy.getName()), copy);
        require(checkpoints(spin) > 0, "real-java-loop-checkpoint");
        System.out.println("SELF_LOOP_CONTROL PASS synthetic-single;reachable-only;deduplicated;unselected;"
                + "unmanaged;initializer;real-java-loop;real-java-self-edge=" + (missedSelfEdge ? 1 : 0)
                + ";GUEST_QUALIFICATION=pending");
    }
}

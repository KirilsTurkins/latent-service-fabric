package org.teavm.dependency;

import java.util.Collection;
import java.util.HashSet;
import java.util.Properties;
import java.util.Set;
import org.teavm.callgraph.CallGraph;
import org.teavm.common.ServiceRepository;
import org.teavm.diagnostics.AccumulationDiagnostics;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.AsyncMethodFinder;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathResourceProvider;

/** JVM-only pinned compiler IR/call-graph controls, never guest execution proof. */
public final class CheckpointContextControl {
    private static final MethodReference CHECKPOINT = new MethodReference(
            "dev.latent.guest.runtime.Activation", "checkpoint", ValueType.VOID);
    private static final MethodReference HELPER = ref("control.Managed", "helper");
    private static final String REFUSAL = "java-checkpoint-nonsuspendable-context-741";

    private static MethodReference ref(String owner, String name) {
        return new MethodReference(owner, name, ValueType.VOID);
    }

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static ClassHolder owner(MutableClassHolderSource source, String name) {
        ClassHolder cls = source.get(name);
        if (cls == null) {
            cls = new ClassHolder(name);
            cls.setParent(name.equals("java.lang.Object") ? null : "java.lang.Object");
            source.putClassHolder(cls);
        }
        return cls;
    }

    private static Program program(MethodReference target) {
        var program = new Program();
        program.createVariable();
        var block = program.createBasicBlock();
        if (target != null) {
            var call = new InvokeInstruction();
            call.setType(InvocationType.SPECIAL);
            call.setMethod(target);
            block.add(call);
        }
        block.add(new ExitInstruction());
        return program;
    }

    private static MethodHolder method(MutableClassHolderSource source, MethodReference reference,
            MethodReference target) {
        var method = new MethodHolder(reference.getDescriptor());
        method.getModifiers().add(ElementModifier.STATIC);
        method.setLevel(AccessLevel.PUBLIC);
        method.setProgram(program(target));
        owner(source, reference.getClassName()).addMethod(method);
        return method;
    }

    private static final class Inputs implements DependencyInfo, ServiceRepository {
        final MutableClassHolderSource source = new MutableClassHolderSource();
        final DefaultCallGraph graph = new DefaultCallGraph();
        final Set<MethodReference> reachable = new HashSet<>();

        Inputs() {
            owner(source, "java.lang.Object");
            method(source, CHECKPOINT, null);
            method(source, HELPER, CHECKPOINT);
            reachable.add(CHECKPOINT);
            reachable.add(HELPER);
            graph.getNode(HELPER).addCallSite(CHECKPOINT);
        }

        void caller(MethodReference reference, MethodReference target) {
            method(source, reference, target);
            reachable.add(reference);
            graph.getNode(reference).addCallSite(target);
        }

        @Override public <T> T getService(Class<T> type) { return null; }
        @Override public ClassReaderSource getClassSource() { return source; }
        @Override public ClassLoader getClassLoader() { return getClass().getClassLoader(); }
        @Override public Collection<MethodReference> getReachableMethods() { return reachable; }
        @Override public Collection<String> getReachableClasses() { return source.getClassNames(); }
        @Override public CallGraph getCallGraph() { return graph; }
        @Override public boolean isPrecise() { return true; }
        @Override public Collection<FieldReference> getReachableFields() { throw new AssertionError("unused-fields"); }
        @Override public FieldDependencyInfo getField(FieldReference field) { throw new AssertionError("unused-field"); }
        @Override public MethodDependencyInfo getMethod(MethodReference method) { throw new AssertionError("unused-method"); }
        @Override public MethodDependencyInfo getMethodImplementation(MethodReference method) {
            throw new AssertionError("unused-implementation");
        }
        @Override public ClassDependencyInfo getClass(String name) { throw new AssertionError("unused-class"); }
    }

    private static void find(Inputs inputs, boolean corrected, String expected) {
        try {
            new AsyncMethodFinder(inputs.graph, inputs).find(inputs.source);
            require(!corrected || expected == null, "unsafe-context-was-accepted");
        } catch (IllegalStateException failure) {
            require(corrected && expected != null && expected.equals(failure.getMessage()),
                    "wrong-or-nonstatic-refusal");
        }
    }

    private static ClassHolder pinnedFiber() throws Exception {
        var jar = java.nio.file.Path.of(org.teavm.runtime.Fiber.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI()).toRealPath();
        try (var provider = org.teavm.parsing.resource.ResourceProvider.ofClassPath(
                java.util.List.of(jar.toFile()))) {
            var source = new PreOptimizingClassHolderSource(
                    new org.teavm.parsing.resource.ResourceBytecodeClassHolderSource(provider, new ReferenceCache()));
            var cls = source.get("org.teavm.runtime.Fiber");
            require(cls != null, "actual-pinned-fiber-class-reader");
            return ModelUtils.copyClass(cls);
        }
    }

    private static void diagnosePinnedEntry(Inputs inputs, MethodReader actual) throws Exception {
        var finder = new AsyncMethodFinder(inputs.graph, inputs);
        var proof = AsyncMethodFinder.class.getDeclaredMethod("pinnedFiberEntry", MethodReader.class);
        proof.setAccessible(true);
        if (Boolean.TRUE.equals(proof.invoke(finder, actual))) return;
        // Failure-only JVM diagnostics for this owned pinned method, never app IR.
        var baseline = pinnedFiber().getMethod(actual.getDescriptor());
        boolean flags = actual.getLevel() == baseline.getLevel();
        for (ElementModifier modifier : ElementModifier.values()) {
            flags &= actual.hasModifier(modifier) == baseline.hasModifier(modifier);
        }
        var bounded = AsyncMethodFinder.class.getDeclaredMethod("boundedFiberEntryBody", ProgramReader.class);
        var body = AsyncMethodFinder.class.getDeclaredMethod("sameFiberEntryBody", ProgramReader.class, ProgramReader.class);
        var instruction = AsyncMethodFinder.class.getDeclaredMethod("sameFiberInstruction", Instruction.class, Instruction.class);
        bounded.setAccessible(true);
        body.setAccessible(true);
        instruction.setAccessible(true);
        var checked = bounded.invoke(finder, actual.getProgram());
        if (!(checked instanceof Program program)) {
            System.err.println("PINNED_ENTRY_PROOF_FAILURE flags=" + flags + ";bounded=false");
            return;
        }
        var opcodes = new java.util.TreeMap<String, Integer>();
        int count = 0;
        for (var block : program.getBasicBlocks()) for (var insn : block) {
            require(++count <= 256, "owned-proof-diagnostic-instruction-bound");
            var name = insn.getClass().getName();
            require(name.startsWith("org.teavm.model.instructions.")
                    && name.substring(29).matches("[A-Za-z]{1,64}"), "owned-proof-diagnostic-opcode");
            String match;
            try {
                match = Boolean.TRUE.equals(instruction.invoke(finder, insn, insn)) ? "equal" : "refused";
            } catch (java.lang.reflect.InvocationTargetException failure) {
                match = failure.getCause() instanceof NullPointerException ? "null-operand" : "exception";
            }
            opcodes.merge(name.substring(29) + ":" + match, 1, Integer::sum);
        }
        String comparison;
        try {
            comparison = "self=" + body.invoke(finder, program, program)
                    + ";baseline=" + body.invoke(finder, baseline.getProgram(), program);
        } catch (java.lang.reflect.InvocationTargetException failure) {
            comparison = failure.getCause() instanceof NullPointerException ? "null-operand" : "exception";
        }
        System.err.println("PINNED_ENTRY_PROOF_FAILURE flags=" + flags
                + ";bounded=true;" + comparison + ";opcodes=" + opcodes);
    }

    private static void graphControls(boolean corrected) throws Exception {
        for (int kind = 0; kind < 4; ++kind) {
            var inputs = new Inputs();
            var caller = ref("control.Unsafe", kind == 0 ? "<clinit>" : "entry");
            inputs.caller(caller, kind == 3 ? CHECKPOINT : HELPER);
            if (kind == 1 || kind == 3) inputs.source.get(caller.getClassName()).getMethod(
                    caller.getDescriptor()).getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
            if (kind == 2) inputs.source.get(caller.getClassName()).getAnnotations().add(
                    new AnnotationHolder("org.teavm.interop.Unmanaged"));
            find(inputs, corrected, REFUSAL);
        }
        var chain = new Inputs();
        var middle = ref("control.Managed", "middle");
        var unsafe = ref("control.Initializer", "<clinit>");
        chain.caller(middle, HELPER);
        chain.caller(unsafe, middle);
        // A second managed caller must not hide the unsafe path of a shared helper.
        chain.caller(ref("control.Managed", "safe"), HELPER);
        find(chain, corrected, REFUSAL);
        require(chain.source.get(HELPER.getClassName()).getMethod(HELPER.getDescriptor())
                .getProgram().basicBlockAt(0).getFirstInstruction() instanceof InvokeInstruction,
                "shared-helper-checkpoint-retained");

        var virtual = new Inputs();
        var caller = ref("control.VirtualCaller", "<clinit>");
        method(virtual.source, caller, null);
        virtual.reachable.add(caller);
        var site = virtual.graph.getNode(HELPER).getVirtualCallSite();
        site.calledMethods.add(virtual.graph.getNode(HELPER));
        virtual.graph.getNode(HELPER).addCaller(site);
        virtual.graph.getNode(caller).addVirtualCallSite(site);
        find(virtual, corrected, REFUSAL);

        var managed = new Inputs();
        var safe = ref("control.Managed", "safe");
        managed.caller(safe, HELPER);
        // A cycle terminates through the independent visited set.
        managed.graph.getNode(HELPER).addCallSite(safe);
        find(managed, corrected, null);
        managed.reachable.remove(CHECKPOINT);
        find(managed, corrected, null);

        var missing = new Inputs();
        var absent = ref("control.Absent", "entry");
        missing.graph.getNode(absent).addCallSite(HELPER);
        find(missing, corrected, "java-checkpoint-unresolved-741");

        var entry = new Inputs();
        var managedEntry = new MethodReference("org.teavm.runtime.Fiber", "start", ValueType.VOID);
        var pinned = pinnedFiber();
        entry.source.putClassHolder(ModelUtils.copyClass(pinned));
        entry.reachable.add(managedEntry);
        var callback = ref("control.ManagedRunner", "run");
        entry.caller(callback, HELPER);
        entry.source.get(callback.getClassName()).getInterfaces().add("org.teavm.runtime.Fiber$FiberRunner");
        entry.source.get(callback.getClassName()).getMethod(callback.getDescriptor())
                .getModifiers().remove(ElementModifier.STATIC);
        // Use the real pinned private entry body and its resolved virtual runner call.
        var runner = ref("org.teavm.runtime.Fiber$FiberRunner", "run");
        var runnerSite = entry.graph.getNode(runner).getVirtualCallSite();
        runnerSite.calledMethods.add(entry.graph.getNode(callback));
        entry.graph.getNode(callback).addCaller(runnerSite);
        entry.graph.getNode(managedEntry).addVirtualCallSite(runnerSite);
        var entryMethod = entry.source.get(managedEntry.getClassName()).getMethod(managedEntry.getDescriptor());
        require(entryMethod.getLevel() == AccessLevel.PRIVATE
                && !entryMethod.hasModifier(ElementModifier.STATIC), "real-private-entry-shape");
        var bootstrap = ref("control.Bootstrap", "<clinit>");
        entry.caller(bootstrap, managedEntry);
        entry.source.get(bootstrap.getClassName()).getAnnotations().add(
                new AnnotationHolder("org.teavm.interop.Unmanaged"));
        if (corrected) diagnosePinnedEntry(entry, entryMethod);
        find(entry, corrected, null);
        boolean replacedNop = false;
        outer: for (var block : entryMethod.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof EmptyInstruction) {
                var unknown = new NullConstantInstruction();
                unknown.setReceiver(entryMethod.getProgram().variableAt(0));
                if (corrected) {
                    var compare = AsyncMethodFinder.class.getDeclaredMethod(
                            "sameFiberInstruction", Instruction.class, Instruction.class);
                    compare.setAccessible(true);
                    require(Boolean.FALSE.equals(compare.invoke(new AsyncMethodFinder(entry.graph, entry),
                            unknown, unknown)), "unknown-opcode-self-comparison-refused");
                }
                instruction.replace(unknown);
                replacedNop = true;
                break outer;
            }
        }
        require(replacedNop, "actual-pinned-nop-replaced-by-unsupported-opcode");
        find(entry, corrected, "java-checkpoint-unresolved-741");
        entry.source.putClassHolder(ModelUtils.copyClass(pinned));
        entryMethod = entry.source.get(managedEntry.getClassName()).getMethod(managedEntry.getDescriptor());
        entryMethod.setProgram(program(null));
        find(entry, corrected, "java-checkpoint-unresolved-741");
        entry.source.putClassHolder(ModelUtils.copyClass(pinned));
        entryMethod = entry.source.get(managedEntry.getClassName()).getMethod(managedEntry.getDescriptor());
        boolean removed = false;
        outer: for (var block : entryMethod.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof PutFieldInstruction put && put.getField().getFieldName().equals("current")
                    && put.getInstance() == null) {
                instruction.delete();
                removed = true;
                break outer;
            }
        }
        require(removed, "actual-current-install-write-removed-negative");
        find(entry, corrected, "java-checkpoint-unresolved-741");
        entry.source.putClassHolder(ModelUtils.copyClass(pinned));
        entryMethod = entry.source.get(managedEntry.getClassName()).getMethod(managedEntry.getDescriptor());
        var handler = new TryCatchBlock();
        handler.setHandler(entryMethod.getProgram().basicBlockAt(0));
        entryMethod.getProgram().basicBlockAt(0).getTryCatchBlocks().add(handler);
        find(entry, corrected, "java-checkpoint-unresolved-741");
        entry.source.putClassHolder(ModelUtils.copyClass(pinned));
        entryMethod = entry.source.get(managedEntry.getClassName()).getMethod(managedEntry.getDescriptor());
        // Same name alone, a public/static method or another overload is no barrier.
        entryMethod.setLevel(AccessLevel.PUBLIC);
        find(entry, corrected, REFUSAL);
        entryMethod.setLevel(AccessLevel.PRIVATE);
        entryMethod.getModifiers().add(ElementModifier.STATIC);
        find(entry, corrected, REFUSAL);
        var overload = new Inputs();
        var other = new MethodReference("org.teavm.runtime.Fiber", "start", ValueType.INTEGER, ValueType.VOID);
        overload.caller(other, HELPER);
        overload.caller(bootstrap, other);
        find(overload, corrected, REFUSAL);

        // Adversarial repeated metadata exercises the edge cap without allocating
        // a huge application. This is a bounded synthetic DefaultCallGraph case.
        var bounded = new Inputs();
        var root = bounded.graph.getNode(CHECKPOINT);
        var repeated = root.getCallerCallSites().iterator().next();
        for (int index = 0; index < 131072; ++index) root.addCaller(repeated);
        find(bounded, corrected, "java-checkpoint-analysis-bound-741");
    }

    private static final class LateBody extends AbstractDependencyListener {
        final MethodReference bridge;
        boolean completed;
        LateBody(MethodReference bridge) { this.bridge = bridge; }
        @Override public void completing(DependencyAgent agent) {
            // Classes must already be linked, but these method edges must be new.
            require(!agent.getReachableMethods().contains(HELPER)
                    && !agent.getReachableMethods().contains(CHECKPOINT), "real-edges-not-reached-before-completion");
            // Real supported completion-time replacement adds an actual analyzer edge.
            agent.submitMethod(bridge, program(HELPER));
            completed = true;
        }
    }

    private static void lateAnalyzerControl(boolean corrected) {
        var inputs = new Inputs();
        var bridge = ref("control.Late", "bridge");
        var nativeMethod = method(inputs.source, bridge, null);
        nativeMethod.setProgram(null);
        nativeMethod.getModifiers().add(ElementModifier.NATIVE);
        var initializer = ref("control.LateInitializer", "<clinit>");
        method(inputs.source, initializer, bridge);
        var diagnostics = new AccumulationDiagnostics();
        var analyzer = new PreciseDependencyAnalyzer(inputs.source,
                new ClasspathResourceProvider(CheckpointContextControl.class.getClassLoader()),
                CheckpointContextControl.class.getClassLoader(), inputs, diagnostics,
                new ReferenceCache(), new String[0], Properties::new);
        var late = new LateBody(bridge);
        analyzer.addDependencyListener(late);
        analyzer.initDependencies();
        // The pinned analyzer forbids first linking a class during completing().
        // Register only these five fixture owners; do not reach helper/checkpoint methods.
        require(inputs.source.getClassNames().size() == 5, "finite-late-fixture-classes");
        for (String name : inputs.source.getClassNames()) analyzer.linkClass(name);
        analyzer.linkMethod(initializer).use();
        analyzer.processDependencies();
        require(late.completed && diagnostics.getSevereProblems().isEmpty(), "real-completion-analysis-finished");
        require(analyzer.getReachableMethods().contains(CHECKPOINT), "real-late-checkpoint-reached");
        var linked = new MutableClassHolderSource();
        for (String name : analyzer.getReachableClasses()) {
            var cls = analyzer.getClassSource().get(name);
            if (cls != null) linked.putClassHolder(ModelUtils.copyClass(cls));
        }
        try {
            new AsyncMethodFinder(analyzer.getCallGraph(), analyzer).find(linked);
            require(!corrected, "real-late-initializer-context-was-accepted");
        } catch (IllegalStateException failure) {
            require(corrected && REFUSAL.equals(failure.getMessage()), "real-late-static-refusal");
        }
    }

    private static void classAnnotationControl() throws Exception {
        var source = new MutableClassHolderSource();
        var method = method(source, ref("control.UnmanagedLoops", "loop"), null);
        var cls = source.get("control.UnmanagedLoops");
        cls.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Unmanaged"));
        var block = method.getProgram().basicBlockAt(0);
        block.getLastInstruction().delete();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        block.add(jump);
        var plugin = new dev.latent.guest.runtime.compiler.RuntimePlugin();
        var classesField = plugin.getClass().getDeclaredField("applicationClasses");
        classesField.setAccessible(true);
        @SuppressWarnings("unchecked") var selected = (Set<String>) classesField.get(plugin);
        selected.add(cls.getName());
        var transform = plugin.getClass().getDeclaredMethod("transform", ClassHolder.class,
                ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        transform.invoke(plugin, cls, null);
        require(block.getFirstInstruction() == jump, "class-unmanaged-loop-not-instrumented");
    }

    public static void main(String[] arguments) throws Exception {
        require(arguments.length == 2 && Set.of("original", "corrected").contains(arguments[0]), "mode");
        require(java.nio.file.Path.of(AsyncMethodFinder.class.getProtectionDomain().getCodeSource()
                .getLocation().toURI()).toRealPath().equals(java.nio.file.Path.of(arguments[1]).toRealPath()),
                "actual-selected-finder-origin");
        require(java.nio.file.Path.of(org.teavm.runtime.Fiber.class.getProtectionDomain().getCodeSource()
                .getLocation().toURI()).toRealPath().equals(java.nio.file.Path.of(arguments[1]).toRealPath()),
                "actual-same-selected-fiber-origin");
        boolean corrected = arguments[0].equals("corrected");
        graphControls(corrected);
        lateAnalyzerControl(corrected);
        classAnnotationControl();
        System.out.println("CHECKPOINT_CONTEXT_CONTROL PASS " + arguments[0]
                + ";direct;multihop;shared;virtual;class-unmanaged;managed-cycle;pinned-managed-entry;altered-entry-negatives;unresolved;bound;real-late-completion");
    }
}

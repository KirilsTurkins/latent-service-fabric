package org.teavm.dependency;

import java.util.Collection;
import java.util.HashSet;
import java.util.Set;
import org.teavm.callgraph.CallGraph;
import org.teavm.model.AnnotationHolder;
import org.teavm.model.AccessLevel;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassReaderSource;
import org.teavm.model.ElementModifier;
import org.teavm.model.FieldReference;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.MutableClassHolderSource;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.MonitorEnterInstruction;
import org.teavm.model.instructions.MonitorExitInstruction;
import org.teavm.model.util.AsyncMethodFinder;
import org.teavm.backend.lowlevel.transform.CoroutineTransformation;

/** Real TeaVM IR and DefaultCallGraph; a finite synthetic compiler mechanism,
 * never a substitute for the six signed original-component outcomes. */
public final class MonitorAsyncControl {
    private static final ValueType OBJECT = ValueType.object("java.lang.Object");
    private static final MethodReference START = new MethodReference(Thread.class, "start", void.class);
    private static final MethodReference PAUSE = new MethodReference("control.Suspend", "pause", ValueType.VOID);
    private static final MethodReference LOCKED = new MethodReference("control.Owner", "locked", OBJECT, ValueType.VOID);
    private static final MethodReference MIXED = new MethodReference("control.Owner", "mixed", OBJECT, ValueType.VOID);
    private static final MethodReference ROOT = new MethodReference("control.Owner", "root", OBJECT, ValueType.VOID);
    private static final MethodReference FAMILY = new MethodReference("control.Contract", "locked", OBJECT, ValueType.VOID);
    private static final MethodReference QUIET = new MethodReference("control.Owner", "quiet", ValueType.VOID);

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static ClassHolder owner(MutableClassHolderSource source, String name) {
        var cls = new ClassHolder(name);
        cls.setParent(name.equals("java.lang.Object") ? null : "java.lang.Object");
        source.putClassHolder(cls);
        return cls;
    }

    private static MethodHolder method(ClassHolder cls, MethodReference reference, boolean pause, boolean monitor) {
        var method = new MethodHolder(reference.getDescriptor());
        method.setLevel(AccessLevel.PUBLIC);
        cls.addMethod(method);
        var program = new Program();
        program.createVariable();
        var object = reference.parameterCount() == 0 ? null : program.createVariable();
        var entry = program.createBasicBlock();
        var block = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        entry.add(jump);
        if (pause) {
            var call = new InvokeInstruction();
            call.setType(InvocationType.SPECIAL);
            call.setMethod(PAUSE);
            block.add(call);
        }
        if (reference.equals(ROOT)) {
            var call = new InvokeInstruction();
            call.setType(InvocationType.SPECIAL);
            call.setMethod(LOCKED);
            call.setInstance(program.variableAt(0));
            call.setArguments(object);
            block.add(call);
        }
        if (monitor) {
            var enter = new MonitorEnterInstruction();
            enter.setObjectRef(object);
            block.add(enter);
            var exit = new MonitorExitInstruction();
            exit.setObjectRef(object);
            block.add(exit);
        }
        block.add(new ExitInstruction());
        method.setProgram(program);
        return method;
    }

    private static final class Inputs implements DependencyInfo {
        final MutableClassHolderSource source = new MutableClassHolderSource();
        final DefaultCallGraph graph = new DefaultCallGraph();
        final Set<MethodReference> reachable = new HashSet<>();
        final MethodHolder locked;
        final MethodHolder mixed;

        Inputs(boolean threads) {
            owner(source, "java.lang.Object");
            var contract = owner(source, "control.Contract");
            contract.getModifiers().add(ElementModifier.INTERFACE);
            contract.getModifiers().add(ElementModifier.ABSTRACT);
            var declaration = new MethodHolder(FAMILY.getDescriptor());
            declaration.getModifiers().add(ElementModifier.ABSTRACT);
            declaration.setLevel(AccessLevel.PUBLIC);
            contract.addMethod(declaration);
            var target = owner(source, "control.Owner");
            target.getInterfaces().add("control.Contract");
            locked = method(target, LOCKED, false, true);
            mixed = method(target, MIXED, true, true);
            method(target, QUIET, false, false);
            method(target, ROOT, false, false);
            var async = new MethodHolder(PAUSE.getDescriptor());
            async.getModifiers().add(ElementModifier.STATIC);
            async.getModifiers().add(ElementModifier.NATIVE);
            async.getAnnotations().add(new AnnotationHolder("org.teavm.interop.Async"));
            owner(source, "control.Suspend").addMethod(async);
            method(owner(source, "java.lang.Thread"), START, false, false);
            reachable.addAll(Set.of(PAUSE, LOCKED, MIXED, ROOT, FAMILY, QUIET));
            if (threads) reachable.add(START);
            // These are actual package-private pinned call-graph writers.
            graph.getNode(MIXED).addCallSite(PAUSE);
            graph.getNode(ROOT).addCallSite(LOCKED);
        }

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

    private static int guardedEntries(Program program) {
        int monitors = 0;
        int guards = 0;
        for (var block : program.getBasicBlocks()) for (var instruction : block) {
            if (!(instruction instanceof MonitorEnterInstruction)) continue;
            monitors++;
            if (instruction.getNext() instanceof InvokeInstruction) {
                var call = (InvokeInstruction) instruction.getNext();
                if (call.getMethod().equals(new MethodReference("org.teavm.runtime.Fiber", "isSuspending",
                        ValueType.BOOLEAN))) guards++;
            }
        }
        require(monitors == 1, "original-monitor-preserved");
        return guards;
    }

    private static void check(String mode, boolean threads) {
        var inputs = new Inputs(threads);
        var finder = new AsyncMethodFinder(inputs.graph, inputs);
        finder.find(inputs.source);
        boolean fixed = mode.equals("corrected") && threads;
        require(finder.hasAsyncMethods() == fixed, "real-thread-monitor-admission");
        require(finder.getAsyncMethods().contains(PAUSE) && finder.getAsyncMethods().contains(MIXED),
                "original-annotated-root-and-caller-preserved");
        require(finder.getAsyncMethods().contains(LOCKED) == fixed, "monitor-only-method");
        require(finder.getAsyncMethods().contains(ROOT) == fixed, "real-monitor-caller-closure");
        require(finder.getAsyncFamilyMethods().contains(FAMILY) == fixed, "real-monitor-family-closure");
        require(!finder.getAsyncMethods().contains(QUIET) && !finder.getAsyncFamilyMethods().contains(QUIET),
                "unrelated-method-not-an-async-root");
        for (var reference : new MethodReference[] {LOCKED, MIXED}) {
            var program = inputs.source.get(reference.getClassName()).getMethod(reference.getDescriptor()).getProgram();
            new CoroutineTransformation(inputs.source, finder.getAsyncMethods(), finder.hasAsyncMethods())
                    .apply(program, reference);
            require(guardedEntries(program) == (fixed ? 1 : 0), "monitor-suspension-boundary");
        }
    }

    public static void main(String[] args) {
        require(args.length == 1 && (args[0].equals("original") || args[0].equals("corrected")), "mode");
        check(args[0], true);
        check(args[0], false);
        System.out.println("{\"schemaVersion\":\"latent.java.monitor-async-control.v1\",\"mode\":\""
                + args[0] + "\",\"passed\":true}");
    }
}

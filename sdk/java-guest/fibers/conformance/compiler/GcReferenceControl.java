package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.backend.lowlevel.transform.WeakReferenceTransformation;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.NullConstantInstruction;
import org.teavm.model.instructions.PutFieldInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Passive real pinned classlib/GC models; separate from actual collection witnesses. */
public final class GcReferenceControl {
    private static final String GC = "org.teavm.runtime.GC";
    private static final String WEAK = "java.lang.ref.WeakReference";
    private static final MethodDescriptor GET = new MethodDescriptor("get", ValueType.object("java.lang.Object"));

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static MethodHolder method(ClassHolder owner, String name, ValueType... signature) {
        require(owner != null, "real-pinned-class-model");
        var method = owner.getMethod(new MethodDescriptor(name, signature));
        require(method != null && method.getProgram() != null, "real-pinned-method-body");
        return method;
    }

    private static Set<MethodReference> calls(MethodHolder method) {
        var result = new HashSet<MethodReference>();
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call) result.add(call.getMethod());
        }
        return result;
    }

    private static MethodReference gc(String name, ValueType... signature) {
        return new MethodReference(GC, name, signature);
    }

    public static void main(String[] arguments) {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            GcReferenceControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var system = source.get("java.lang.System");
        var standard = method(system, "gc", ValueType.VOID);
        var delegate = standard.getAnnotations().get("org.teavm.interop.DelegateTo");
        require(delegate != null && delegate.getValue("value").getString().equals("gcLowLevel"),
            "standard-gc-selected-lowlevel-delegate");
        require(calls(method(system, "gcLowLevel", ValueType.VOID)).equals(
            Set.of(gc("collectGarbageFull", ValueType.VOID))), "real-full-gc-entry");
        var collector = source.get(GC);
        require(calls(method(collector, "collectGarbageFull", ValueType.VOID)).equals(Set.of(
            gc("fixHeap", ValueType.VOID), gc("collectGarbageFullImpl", ValueType.INTEGER, ValueType.VOID))),
            "real-full-gc-not-empty");
        require(calls(method(collector, "collectGarbageFullImpl", ValueType.INTEGER, ValueType.VOID)).equals(Set.of(
            gc("triggerFullGC", ValueType.VOID), gc("collectGarbageImpl", ValueType.INTEGER, ValueType.VOID))),
            "real-full-gc-trigger-and-collector");
        require(calls(method(collector, "collectGarbageImpl", ValueType.INTEGER, ValueType.VOID)).contains(
            gc("doCollectGarbage", ValueType.VOID)), "real-collection-body-reachable");
        var bodyCalls = calls(method(collector, "doCollectGarbage", ValueType.VOID));
        require(bodyCalls.containsAll(Set.of(gc("mark", ValueType.VOID),
            gc("processReferences", ValueType.VOID), gc("sweep", ValueType.VOID))),
            "real-mark-reference-processing-and-sweep");
        var references = method(collector, "processReferences", ValueType.VOID);
        require(calls(references).contains(gc("isMarked", ValueType.object("org.teavm.runtime.RuntimeObject"),
            ValueType.BOOLEAN)), "weak-clearing-reads-real-mark-status");
        var nulls = new HashSet<Variable>();
        for (var block : references.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof NullConstantInstruction value) nulls.add(value.getReceiver());
        }
        boolean clearsReferent = false;
        for (var block : references.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof PutFieldInstruction store
                    && store.getField().getClassName().equals("org.teavm.runtime.RuntimeReference")
                    && store.getField().getFieldName().equals("object") && nulls.contains(store.getValue())) {
                clearsReferent = true;
            }
        }
        require(clearsReferent, "real-collector-clears-unmarked-weak-referent");

        var originalWeak = source.get(WEAK);
        require(originalWeak != null && !originalWeak.getFields().isEmpty()
            && originalWeak.getMethod(GET).getProgram() != null, "real-classlib-weak-reference-preimage");
        var selected = ModelUtils.copyClass(originalWeak);
        var transformer = new WeakReferenceTransformation();
        transformer.transformClass(selected, null);
        require(selected.getFields().isEmpty() && !selected.getMethods().isEmpty(),
            "actual-lowlevel-weak-layout-selection");
        for (var method : selected.getMethods()) {
            require(method.getProgram() == null && method.getModifiers().contains(ElementModifier.NATIVE)
                && method.getAnnotations().get("org.teavm.interop.Intrinsified") != null,
                "actual-lowlevel-reference-method-generation");
        }
        require(!originalWeak.getFields().isEmpty() && originalWeak.getMethod(GET).getProgram() != null,
            "original-weak-model-unchanged");
        var unrelated = ModelUtils.copyClass(system);
        var unchanged = unrelated.getMethod(new MethodDescriptor("gcLowLevel", ValueType.VOID)).getProgram();
        transformer.transformClass(unrelated, null);
        require(unrelated.getMethod(new MethodDescriptor("gcLowLevel", ValueType.VOID)).getProgram() == unchanged,
            "unrelated-class-transform-negative");
        System.out.println("GC_REFERENCE_CONTROL PASS real-full-gc-delegate;mark-weak-clear-sweep;"
            + "lowlevel-reference-layout;original-unrelated-negatives;runtime-witness-separate");
    }
}

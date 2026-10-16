package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Resolve the actual pinned compiler's API, helper and field identities. */
public final class StandardTimerModelControl {
    private static final String ENTRY = "dev.latent.guest.runtime.util.Timer$Entry";
    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }
    private static boolean owned(String name) {
        return name.equals("java.util.Timer") || name.equals("java.util.TimerTask") || name.equals(ENTRY);
    }
    private static void canonical(ValueType type) {
        if (type instanceof ValueType.Array array) canonical(array.getItemType());
        else if (type instanceof ValueType.Object object) {
            String name = object.getClassName();
            require(!name.equals("dev.latent.guest.runtime.util.Timer")
                && !name.equals("dev.latent.guest.runtime.util.TimerTask")
                && !name.equals("java.util.Timer$Entry"), "noncanonical-timer-type:" + name);
        }
    }
    private static void field(ClassReaderSource source, FieldReference reference, ValueType type) {
        canonical(type);
        if (!owned(reference.getClassName())) return;
        ClassReader owner = source.get(reference.getClassName());
        FieldReader field = owner == null ? null : owner.getField(reference.getFieldName());
        require(field != null && field.getType().equals(type), "unresolved-timer-field:" + reference);
    }
    public static void main(String[] args) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(StandardTimerModelControl.class.getClassLoader()),
            new ReferenceCache(), DefaultSubstituteClassNameMapping.createWithPolicies(
                List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        var models = List.of(source.get("java.util.Timer"), source.get("java.util.TimerTask"), source.get(ENTRY));
        require(models.get(0).getField("tasks") != null && models.get(0).getField("pendingWork") == null
            && models.get(1).getField("nativeTimerId") != null && models.get(1).getField("lastScheduled") == null,
                "actual-original-classlib-negative");
        ClassHolderTransformerContext context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder model) { throw new AssertionError("submit"); }
        };
        for (ClassHolder model : models.subList(0, 2)) {
            ClassHolder wrong = ModelUtils.copyClass(model);
            wrong.getField(model.getName().equals("java.util.Timer") ? "tasks" : "nativeTimerId").setType(ValueType.LONG);
            try { StandardTimerMethods.transform(wrong, context); throw new AssertionError("layout-negative-not-rejected"); }
            catch (IllegalStateException expected) { }
            StandardTimerMethods.transform(model, context);
            try { StandardTimerMethods.transform(model, context); throw new AssertionError("repeat-negative-not-rejected"); }
            catch (IllegalStateException expected) { }
        }
        require(models.get(0).getField("pendingWork") != null && models.get(1).getField("lastScheduled") != null,
                "actual-SDK-timer-models-selected");
        require(models.get(2).getName().equals(ENTRY), "single-private-timer-helper-identity");
        var normalize = RuntimePlugin.class.getDeclaredMethod("normalizeOwnedTimerReferences", ClassHolder.class);
        normalize.setAccessible(true);
        for (ClassHolder model : models) normalize.invoke(null, model);
        int bodies = 0, references = 0;
        for (ClassHolder model : models) {
            for (FieldHolder declaration : model.getFields()) canonical(declaration.getType());
            for (MethodHolder method : model.getMethods()) {
                for (ValueType type : method.getDescriptor().getSignature()) canonical(type);
                if (method.getProgram() == null) continue;
                bodies++;
                for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                    if (instruction instanceof InvokeInstruction invoke) {
                        var target = invoke.getMethod();
                        for (ValueType type : target.getDescriptor().getSignature()) canonical(type);
                        require(!target.getClassName().equals("java.util.Timer$Entry"), "no-standard-helper-call-alias");
                        if (owned(target.getClassName())) {
                            require(new ClassHierarchy(source).resolve(target.getClassName(), target.getDescriptor()) != null,
                                    "unresolved-timer-call:" + target);
                            references++;
                        }
                    } else if (instruction instanceof GetFieldInstruction read) {
                        field(source, read.getField(), read.getFieldType());
                    } else if (instruction instanceof PutFieldInstruction write) {
                        field(source, write.getField(), write.getFieldType());
                    } else if (instruction instanceof ConstructInstruction construct) {
                        require(!construct.getType().equals("java.util.Timer$Entry"), "no-standard-helper-construction-alias");
                    }
                }
            }
        }
        require(bodies >= 20 && references >= 10, "complete-timer-model-closure");
        require(source.get("java.util.Timer").getMethod(new MethodDescriptor("absentControlMethod", ValueType.VOID)) == null,
                "unsupported-timer-member-no-fallback");
        System.out.println("STANDARD_TIMER_MODEL_CONTROL PASS original-classlib-negative;layout-and-repeat-negatives;canonical-api-and-private-helper;resolved-method-and-field-types;unsupported-no-fallback;models=3");
    }
}

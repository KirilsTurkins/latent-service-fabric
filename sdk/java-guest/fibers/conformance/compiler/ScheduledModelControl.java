package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Actual pinned TeaVM models, including the private scheduled-task identity. */
public final class ScheduledModelControl {
    private static final String STANDARD = RuntimeSubstitution.STANDARD;
    private static final String TASK = RuntimeSubstitution.SDK + "ScheduledThreadPoolExecutor$Task";
    private static void require(boolean value, String why) { if (!value) throw new AssertionError(why); }
    private static boolean owned(String name) {
        return name.equals(TASK) || name.startsWith(STANDARD)
            && RuntimeSubstitution.API.contains(name.substring(STANDARD.length()));
    }
    private static void canonical(ValueType type) {
        if (type instanceof ValueType.Array array) canonical(array.getItemType());
        else if (type instanceof ValueType.Object object && object.getClassName().startsWith(RuntimeSubstitution.SDK))
            require(!RuntimeSubstitution.API.contains(object.getClassName().substring(RuntimeSubstitution.SDK.length())),
                "scheduled-public-type-alias:" + object.getClassName());
    }
    private static MethodReader method(ClassReaderSource source, String name, MethodDescriptor descriptor, Set<String> seen) {
        if (!seen.add(name)) return null;
        ClassReader model = source.get(name);
        if (model == null) return null;
        MethodReader found = model.getMethod(descriptor);
        if (found != null) return found;
        for (String parent : model.getInterfaces()) {
            found = method(source, parent, descriptor, seen);
            if (found != null) return found;
        }
        return model.getParent() == null ? null : method(source, model.getParent(), descriptor, seen);
    }
    private static FieldReader field(ClassReaderSource source, String name, String field, Set<String> seen) {
        if (!seen.add(name)) return null;
        ClassReader model = source.get(name);
        if (model == null) return null;
        FieldReader found = model.getField(field);
        if (found != null) return found;
        return model.getParent() == null ? null : field(source, model.getParent(), field, seen);
    }
    public static void main(String[] args) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(ScheduledModelControl.class.getClassLoader()),
            new ReferenceCache(), DefaultSubstituteClassNameMapping.createWithPolicies(
                List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        var models = new java.util.ArrayList<ClassHolder>();
        for (String name : List.of("Delayed", "ScheduledFuture", "ScheduledExecutorService", "ScheduledThreadPoolExecutor",
                "Executors", "FutureTask")) {
            ClassHolder model = source.get(STANDARD + name);
            require(model != null, "missing-standard-scheduled-model:" + name); models.add(model);
        }
        ClassHolder task = source.get(TASK);
        require(task != null && task.getName().equals(TASK), "missing-private-scheduled-task"); models.add(task);
        ClassHolderTransformerContext context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder model) { throw new AssertionError("submit"); }
        };
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class, ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        var plugin = new RuntimePlugin();
        for (ClassHolder model : models) transform.invoke(plugin, model, context);
        ClassHolder pool = models.get(3);
        require(pool.getField("pendingWork") != null && pool.getField("owner") != null,
            "actual-owned-scheduled-body-selected");
        require(task.getParent().equals(STANDARD + "FutureTask"), "canonical-task-parent");
        require(pool.getMethod(new MethodDescriptor("<init>", ValueType.INTEGER, ValueType.VOID)) != null,
            "ordinary-published-constructor");
        for (ClassHolder model : models) {
            for (FieldHolder declaration : model.getFields()) canonical(declaration.getType());
            for (MethodHolder body : model.getMethods()) {
                for (ValueType type : body.getDescriptor().getSignature()) canonical(type);
                if (body.getProgram() == null) continue;
                for (BasicBlock block : body.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                    if (instruction instanceof InvokeInstruction call && owned(call.getMethod().getClassName())) {
                        require(method(source, call.getMethod().getClassName(), call.getMethod().getDescriptor(), new HashSet<>()) != null,
                            "unresolved-scheduled-method:" + call.getMethod());
                    }
                    FieldReference reference = null;
                    ValueType type = null;
                    if (instruction instanceof GetFieldInstruction read) { reference = read.getField(); type = read.getFieldType(); }
                    else if (instruction instanceof PutFieldInstruction write) { reference = write.getField(); type = write.getFieldType(); }
                    if (reference != null && owned(reference.getClassName())) {
                        FieldReader actual = field(source, reference.getClassName(), reference.getFieldName(), new HashSet<>());
                        require(actual != null && actual.getType().equals(type), "unresolved-scheduled-field:" + reference);
                        canonical(type);
                    }
                }
            }
        }
        require(method(source, STANDARD + "ScheduledThreadPoolExecutor",
            new MethodDescriptor("unsupportedControlMember", ValueType.VOID), new HashSet<>()) == null,
            "unsupported-has-no-original-fallback");
        System.out.println("SCHEDULED_MODEL_CONTROL PASS standard-APIs;private-task;canonical-fields-and-methods;ordinary-constructor;no-fallback;models=7");
    }
}

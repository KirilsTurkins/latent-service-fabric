package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.classlib.impl.lambda.LambdaMetafactorySubstitutor;
import org.teavm.dependency.LambdaEmitterControlContext;
import org.teavm.model.*;
import org.teavm.model.emit.ProgramEmitter;
import org.teavm.model.emit.ValueEmitter;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Actual pinned TeaVM models, including the private scheduled-task identity. */
public final class ScheduledModelControl {
    private static final String STANDARD = RuntimeSubstitution.STANDARD;
    private static final String TASK = RuntimeSubstitution.SDK + "ScheduledThreadPoolExecutor$Task";
    private static final String MANAGED = RuntimeSubstitution.SDK + "ManagedExecutor";
    private static void require(boolean value, String why) { if (!value) throw new AssertionError(why); }
    private static boolean owned(String name) {
        return name.equals(TASK) || name.equals(MANAGED) || name.startsWith(STANDARD)
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
    private static void constructedIdentities(ClassHolder original) throws Exception {
        String[] before = {STANDARD + "Executors$callable$lambda$_13_0",
            STANDARD + "ScheduledThreadPoolExecutor$startWorker$lambda$_6_0",
            RuntimeSubstitution.SDK + "ManagedExecutor$startWorker$lambda$_6_0",
            STANDARD + "ScheduledThreadPoolExecutor$Task", STANDARD + "Executors$1"};
        String[] expected = {before[0], before[1], before[2], TASK, RuntimeSubstitution.SDK + "Executors$1"};
        ClassHolder carrier = ModelUtils.copyClass(original);
        MethodHolder method = new MethodHolder("constructedCallbackIdentityControl", ValueType.VOID);
        method.getModifiers().add(ElementModifier.STATIC);
        Program program = new Program(); program.createVariable();
        BasicBlock block = program.createBasicBlock();
        for (String name : before) {
            ConstructInstruction construct = new ConstructInstruction();
            construct.setType(name); construct.setReceiver(program.createVariable()); block.add(construct);
        }
        block.add(new ExitInstruction()); method.setProgram(program); carrier.addMethod(method);
        var normalize = RuntimePlugin.class.getDeclaredMethod("normalizeOwnedConcurrentReferences", ClassHolder.class);
        normalize.setAccessible(true); normalize.invoke(null, carrier);
        int count = 0;
        for (Instruction instruction : method.getProgram().basicBlockAt(0))
            if (instruction instanceof ConstructInstruction construct)
                require(construct.getType().equals(expected[count++]), "actual-observed-construction-identity");
        require(count == 5, "complete-observed-construction-identity");
    }
    private static void generatedCallback(ClassHolder owner, String methodName, ClassReaderSource source) throws Exception {
        var collector = new LambdaEmitterControlContext(source);
        var factory = new LambdaMetafactorySubstitutor();
        var normalize = RuntimePlugin.class.getDeclaredMethod("normalizeOwnedConcurrentReferences", ClassHolder.class);
        normalize.setAccessible(true);
        int callbacks = 0;
        for (MethodHolder method : owner.getMethods()) {
            if (!method.getName().equals(methodName) || method.getProgram() == null) continue;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (!(instruction instanceof InvokeDynamicInstruction dynamic)
                        || !dynamic.getBootstrapMethod().getClassName().equals("java.lang.invoke.LambdaMetafactory")) continue;
                var emitter = ProgramEmitter.create(new MethodDescriptor("probe", ValueType.VOID), collector.getClassHierarchy());
                List<ValueEmitter> captures = new java.util.ArrayList<>();
                for (int i = 0; i < dynamic.getMethod().parameterCount(); ++i)
                    captures.add(emitter.newVar(dynamic.getMethod().parameterType(i)));
                factory.substitute(collector.site(method.getReference(), dynamic, captures), emitter);
                ClassHolder replay = new ClassHolder(owner.getName());
                MethodHolder body = new MethodHolder(method.getDescriptor());
                body.setProgram(emitter.getProgram()); replay.addMethod(body); normalize.invoke(null, replay);
                int constructions = 0;
                for (BasicBlock emittedBlock : body.getProgram().getBasicBlocks()) for (Instruction emitted : emittedBlock) {
                    if (emitted instanceof ConstructInstruction construct) {
                        require(collector.generated.containsKey(construct.getType()), "actual-generated-callback-reference:" + construct.getType());
                        require(construct.getType().startsWith(owner.getName() + "$"), "actual-generated-callback-namespace");
                        constructions++;
                    }
                    if (emitted instanceof InvokeInstruction invoke && invoke.getMethod().getName().equals("<init>"))
                        require(collector.generated.containsKey(invoke.getMethod().getClassName()), "actual-generated-callback-constructor");
                }
                require(constructions == 1, "one-actual-generated-callback"); callbacks++;
            }
        }
        require(callbacks == 1 && collector.generated.size() == 1, "complete-actual-generated-callback");
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
        ClassHolder managed = source.get(MANAGED);
        require(managed != null, "missing-SDK-origin-worker-model"); models.add(managed);
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
        constructedIdentities(models.get(4));
        generatedCallback(models.get(4), "callable", source);
        generatedCallback(models.get(3), "startWorker", source);
        generatedCallback(managed, "startWorker", source);
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
        System.out.println("SCHEDULED_MODEL_CONTROL PASS standard-APIs;private-task;canonical-fields-and-methods;ordinary-constructor;no-fallback;constructed-identities=5;actual-generated-callbacks=3;models=8");
    }
}

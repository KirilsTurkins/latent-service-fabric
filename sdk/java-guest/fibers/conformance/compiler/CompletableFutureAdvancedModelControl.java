package dev.latent.guest.runtime.compiler;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.backend.lowlevel.transform.CoroutineTransformation;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Independent advanced-profile inspection. The maintained old guard is unchanged. */
public final class CompletableFutureAdvancedModelControl {
    private static final String STANDARD = RuntimeSubstitution.STANDARD;
    private static final String SDK = RuntimeSubstitution.SDK;
    private static final ValueType FUTURE = ValueType.object(STANDARD + "CompletableFuture");
    private static final ValueType UNIT = ValueType.object(STANDARD + "TimeUnit");
    private static final ValueType EXECUTOR = ValueType.object(STANDARD + "Executor");
    private static final List<String> HELPERS = List.of("Action", "Aggregate", "DefaultExecutor",
        "Timeout", "Canceller", "DeferredCommand", "DelayedExecutor", "DelayedSubmission", "DelayedDelivery");

    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }
    private static void canonical(ValueType type) {
        if (type instanceof ValueType.Array array) canonical(array.getItemType());
        else if (type instanceof ValueType.Object object && object.getClassName().startsWith(SDK))
            require(!RuntimeSubstitution.API.contains(object.getClassName().substring(SDK.length())),
                "advanced-no-public-SDK-type-alias:" + object.getClassName());
    }
    private static boolean owned(String name) {
        return name.startsWith(STANDARD) && RuntimeSubstitution.API.contains(name.substring(STANDARD.length()))
            || name.startsWith(SDK + "CompletableFuture$")
                && HELPERS.contains(name.substring((SDK + "CompletableFuture$").length()));
    }
    private static void references(ClassHolder model, ClasspathClassHolderSource source) {
        var hierarchy = new ClassHierarchy(source);
        for (FieldHolder field : model.getFields()) canonical(field.getType());
        for (MethodHolder method : model.getMethods()) {
            for (ValueType type : method.getDescriptor().getSignature()) canonical(type);
            if (method.getProgram() == null) continue;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (instruction instanceof InvokeInstruction invoke) {
                    MethodReference target = invoke.getMethod();
                    require(!target.getClassName().startsWith(SDK)
                        || !RuntimeSubstitution.API.contains(target.getClassName().substring(SDK.length())),
                        "advanced-no-public-SDK-call-alias:" + target);
                    for (ValueType type : target.getDescriptor().getSignature()) canonical(type);
                    if (owned(target.getClassName()))
                        require(hierarchy.resolve(target.getClassName(), target.getDescriptor()) != null,
                            "advanced-resolved-owned-method:" + target);
                } else if (instruction instanceof ConstructInstruction construct && owned(construct.getType())) {
                    require(source.get(construct.getType()) != null, "advanced-resolved-owned-construction");
                } else if (instruction instanceof GetFieldInstruction field && owned(field.getField().getClassName())) {
                    FieldReader resolved = hierarchy.resolve(field.getField());
                    require(resolved != null && resolved.getType().equals(field.getFieldType()),
                        "advanced-resolved-owned-read:" + field.getField());
                    canonical(field.getFieldType());
                } else if (instruction instanceof PutFieldInstruction field && owned(field.getField().getClassName())) {
                    FieldReader resolved = hierarchy.resolve(field.getField());
                    require(resolved != null && resolved.getType().equals(field.getFieldType()),
                        "advanced-resolved-owned-write:" + field.getField());
                    canonical(field.getFieldType());
                }
            }
        }
    }
    private static void method(ClassHolder future, MethodDescriptor descriptor) {
        MethodHolder body = future.getMethod(descriptor);
        require(body != null && body.getProgram() != null, "advanced-real-method-body:" + descriptor);
    }
    public static void main(String[] args) throws Exception {
        ClassLoader loader = CompletableFutureAdvancedModelControl.class.getClassLoader();
        for (String name : List.of("CompletableFuture", "CompletionStage", "CompletionException"))
            require(loader.getResource("org/teavm/classlib/java/util/concurrent/T" + name + ".class") == null,
                "advanced-actual-maintained-missing-class-negative");
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        ClassHolder future = source.get(STANDARD + "CompletableFuture");
        ClassHolder stage = source.get(STANDARD + "CompletionStage");
        ClassHolder exception = source.get(STANDARD + "CompletionException");
        require(future != null && stage != null && exception != null, "advanced-actual-SDK-models-selected");
        require(future.getField("accepted") != null && future.getField("resultOwner") != null,
            "advanced-original-owned-port-layout");
        require(future.getInterfaces().contains(STANDARD + "Future")
            && future.getInterfaces().contains(STANDARD + "CompletionStage"), "advanced-canonical-interface-identities");
        require(stage.hasModifier(ElementModifier.INTERFACE)
            && exception.getParent().equals("java.lang.RuntimeException"), "advanced-standard-hierarchy");

        List<ClassHolder> models = new ArrayList<>(List.of(future, stage, exception));
        for (String name : HELPERS) {
            String identity = SDK + "CompletableFuture$" + name;
            ClassHolder helper = source.get(identity);
            require(helper != null && helper.getName().equals(identity), "advanced-one-private-helper-identity:" + name);
            models.add(helper);
        }
        require(source.get(SDK + "CompletableFuture$DeferredCommand").hasModifier(ElementModifier.INTERFACE),
            "advanced-owned-queue-witness-interface");
        ClassHolderTransformerContext context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder cls) { throw new AssertionError("submit"); }
        };
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class, ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        var plugin = new RuntimePlugin();
        for (ClassHolder model : models) {
            String identity = model.getName();
            transform.invoke(plugin, model, context);
            require(model.getName().equals(identity), "advanced-model-identity-preserved");
        }
        for (ClassHolder model : models) references(model, source);
        var hierarchy = new ClassHierarchy(source);
        FieldReader inherited = hierarchy.resolve(SDK + "CompletableFuture$Aggregate", "both");
        require(inherited != null && inherited.getType().equals(ValueType.BOOLEAN)
            && inherited.getReference().getClassName().equals(SDK + "CompletableFuture$Action"),
            "advanced-real-inherited-owned-field");
        require(hierarchy.resolve(SDK + "CompletableFuture$Aggregate", "absentControlField") == null,
            "advanced-unresolved-owned-field-rejected");
        method(future, new MethodDescriptor("orTimeout", ValueType.LONG, UNIT, FUTURE));
        method(future, new MethodDescriptor("completeOnTimeout", ValueType.object("java.lang.Object"), ValueType.LONG, UNIT, FUTURE));
        method(future, new MethodDescriptor("delayedExecutor", ValueType.LONG, UNIT, EXECUTOR));
        method(future, new MethodDescriptor("delayedExecutor", ValueType.LONG, UNIT, EXECUTOR, EXECUTOR));
        require(future.getMethod(new MethodDescriptor("obtrudeValue", ValueType.object("java.lang.Object"), ValueType.VOID)) == null,
            "advanced-unsupported-obtrusion-no-fallback");
        require(future.getMethod(new MethodDescriptor("minimalCompletionStage", ValueType.object(STANDARD + "CompletionStage"))) == null,
            "advanced-unsupported-minimal-stage-no-fallback");

        // Reuse the exact locked-emitter closure checks; never synthesize callbacks.
        var generated = CompletableFutureModelControl.class.getDeclaredMethod("generatedCallbacks", ClassHolder.class, ClassReaderSource.class);
        generated.setAccessible(true);
        int callbacks = (Integer)generated.invoke(null, future, source);
        Set<MethodReference> suspends = new HashSet<>(Set.of(
            new MethodReference("java.lang.Object", "wait", ValueType.VOID),
            new MethodReference("java.lang.Object", "wait", ValueType.LONG, ValueType.INTEGER, ValueType.VOID),
            new MethodReference("java.lang.Thread", "sleep", ValueType.LONG, ValueType.VOID),
            new MethodReference("java.lang.Thread", "sleep", ValueType.LONG, ValueType.INTEGER, ValueType.VOID)));
        for (ClassHolder model : models) for (MethodHolder method : model.getMethods()) {
            if (method.getProgram() == null) continue;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (!(instruction instanceof InvokeInstruction invoke)) continue;
                MethodReference target = invoke.getMethod();
                MethodReader resolved = new ClassHierarchy(source).resolve(target.getClassName(), target.getDescriptor());
                if (target.getName().equals("wait") && resolved != null
                        && resolved.getReference().getClassName().equals("java.lang.Object")
                    || target.getClassName().equals("dev.latent.guest.runtime.Activation$Lease") && target.getName().equals("close")
                    || target.getClassName().equals("dev.latent.guest.runtime.Activation") && target.getName().equals("owner"))
                    suspends.add(target);
            }
        }
        int bodies = 0, lowered = 0, monitorBodies = 0;
        Set<MethodReference> loweredMethods = new HashSet<>();
        for (ClassHolder model : models) for (MethodHolder method : model.getMethods()) {
            if (method.getProgram() == null) continue;
            bodies++;
            boolean monitor = false, ownedCall = false;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (instruction instanceof MonitorEnterInstruction) monitor = true;
                if (instruction instanceof InvokeInstruction invoke && suspends.contains(invoke.getMethod())) ownedCall = true;
            }
            if (!monitor && !ownedCall) continue;
            Program loweredProgram = ProgramUtils.copy(method.getProgram());
            new CoroutineTransformation(source, suspends, true).apply(loweredProgram, method.getReference());
            require(loweredProgram.basicBlockCount() > method.getProgram().basicBlockCount(), "advanced-actual-resumption-split:" + method.getReference());
            if (monitor) monitorBodies++;
            loweredMethods.add(method.getReference());
            lowered++;
        }
        require(bodies >= 100 && lowered >= 15, "advanced-preserved-original-closure-minima");
        for (String helper : List.of("Timeout", "DelayedSubmission"))
            require(loweredMethods.contains(new MethodReference(SDK + "CompletableFuture$" + helper, "run", ValueType.VOID)),
                "advanced-real-deadline-body-lowered:" + helper);
        require(loweredMethods.contains(new MethodReference(SDK + "CompletableFuture$DelayedSubmission", "awaitRetirement", ValueType.VOID)),
            "advanced-real-physical-retirement-wait-lowered");
        ClassHolder unrelated = new ClassHolder("outside.library.CompletableFuture");
        MethodHolder untouched = new MethodHolder("untouched", ValueType.VOID);
        Program original = new Program(); original.createVariable(); original.createBasicBlock().add(new ExitInstruction());
        untouched.setProgram(original); unrelated.addMethod(untouched);
        transform.invoke(plugin, unrelated, context);
        require(untouched.getProgram() == original && original.basicBlockCount() == 1, "advanced-application-model-identity-preserved");
        System.out.println("COMPLETABLE_FUTURE_ADVANCED_MODEL_CONTROL PASS actual-methods=4;actual-helpers=" + HELPERS.size()
            + ";bodies=" + bodies + ";coroutine-monitors=" + monitorBodies + ";owned-coroutines=" + lowered
            + ";actual-generated-callbacks=" + callbacks + ";unsupported-obtrusion-and-minimal-stage;physical-wait-lowered;application-identity");
    }
}

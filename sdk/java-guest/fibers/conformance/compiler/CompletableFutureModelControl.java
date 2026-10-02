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

/** Read actual locked TeaVM IR without initializing the port or application classes. */
public final class CompletableFutureModelControl {
    private static final String STANDARD = "java.util.concurrent.";
    private static final String SDK = "dev.latent.guest.runtime.concurrent.";
    private static int methods;
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
    private static boolean port(String name) {
        return name.equals("CompletableFuture") || name.equals("CompletionStage") || name.equals("CompletionException");
    }
    private static void canonical(ValueType type) {
        if (type instanceof ValueType.Array array) canonical(array.getItemType());
        else if (type instanceof ValueType.Object object && object.getClassName().startsWith(SDK))
            require(!port(object.getClassName().substring(SDK.length())), "no-public-SDK-type-alias");
    }
    private static void closure(ClassHolder cls, ClasspathClassHolderSource source) {
        for (FieldHolder field : cls.getFields()) canonical(field.getType());
        for (MethodHolder method : cls.getMethods()) {
            for (ValueType type : method.getDescriptor().getSignature()) canonical(type);
            Program program = method.getProgram();
            if (program == null) continue;
            methods++;
            for (BasicBlock block : program.getBasicBlocks()) for (Instruction instruction : block) {
                if (instruction instanceof InvokeInstruction invoke) {
                    MethodReference target = invoke.getMethod();
                    if (target.getClassName().startsWith(SDK))
                        require(!port(target.getClassName().substring(SDK.length())), "no-public-SDK-call-alias");
                    for (ValueType type : target.getDescriptor().getSignature()) canonical(type);
                    if (target.getClassName().startsWith(STANDARD)
                            && port(target.getClassName().substring(STANDARD.length())))
                        require(new ClassHierarchy(source).resolve(target.getClassName(), target.getDescriptor()) != null,
                                "resolved-standard-method:" + target);
                } else if (instruction instanceof GetFieldInstruction field) {
                    if (field.getField().getClassName().equals(STANDARD + "CompletableFuture"))
                        require(source.get(field.getField().getClassName()).getField(field.getField().getFieldName()) != null,
                                "resolved-standard-field");
                } else if (instruction instanceof PutFieldInstruction field) {
                    if (field.getField().getClassName().equals(STANDARD + "CompletableFuture"))
                        require(source.get(field.getField().getClassName()).getField(field.getField().getFieldName()) != null,
                                "resolved-standard-field");
                }
            }
        }
    }
    public static void main(String[] args) throws Exception {
        ClassLoader loader = CompletableFutureModelControl.class.getClassLoader();
        for (String name : List.of("CompletableFuture", "CompletionStage", "CompletionException"))
            require(loader.getResource("org/teavm/classlib/java/util/concurrent/T" + name + ".class") == null,
                    "actual-maintained-missing-class-negative");
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        ClassHolder future = source.get(STANDARD + "CompletableFuture");
        ClassHolder stage = source.get(STANDARD + "CompletionStage");
        ClassHolder exception = source.get(STANDARD + "CompletionException");
        require(future != null && stage != null && exception != null, "actual-SDK-models-selected");
        require(future.getField("accepted") != null && future.getField("resultOwner") != null,
                "actual-owned-port-field-layout");
        MethodDescriptor get = new MethodDescriptor("get", ValueType.object("java.lang.Object"));
        MethodHolder originalGet = future.getMethod(get);
        require(originalGet != null && originalGet.getProgram() != null, "actual-pending-get-body");
        Set<MethodReference> suspends = new HashSet<>(Set.of(
            new MethodReference("java.lang.Object", "wait", ValueType.VOID),
            new MethodReference("java.lang.Object", "wait", ValueType.LONG, ValueType.INTEGER, ValueType.VOID)));
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
        List<ClassHolder> models = new ArrayList<>(List.of(future, stage, exception));
        for (String name : List.of("Action", "Aggregate", "DefaultExecutor")) {
            ClassHolder helper = source.get(SDK + "CompletableFuture$" + name);
            require(helper != null && helper.getName().equals(SDK + "CompletableFuture$" + name), "one-private-helper-identity");
            models.add(helper);
        }
        for (ClassHolder cls : models) transform.invoke(plugin, cls, context);
        for (ClassHolder cls : models) for (MethodHolder method : cls.getMethods()) {
            if (method.getProgram() == null) continue;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (!(instruction instanceof InvokeInstruction invoke)) continue;
                MethodReference target = invoke.getMethod();
                MethodReader resolved = new ClassHierarchy(source).resolve(target.getClassName(), target.getDescriptor());
                boolean wait = target.getName().equals("wait") && resolved != null
                    && resolved.getReference().getClassName().equals("java.lang.Object");
                boolean lease = target.getClassName().equals("dev.latent.guest.runtime.Activation$Lease") && target.getName().equals("close");
                boolean admission = target.getClassName().equals("dev.latent.guest.runtime.Activation") && target.getName().equals("owner");
                if (wait || lease || admission) suspends.add(target);
            }
        }
        require(future.getInterfaces().contains(STANDARD + "Future") && future.getInterfaces().contains(STANDARD + "CompletionStage"),
                "canonical-standard-interface-identities");
        require(stage.hasModifier(ElementModifier.INTERFACE) && exception.getParent().equals("java.lang.RuntimeException"),
                "standard-stage-and-exception-hierarchy");
        for (ClassHolder cls : models) closure(cls, source);
        require(methods >= 100, "complete-port-model-body-closure");
        require(future.getMethod(new MethodDescriptor("orTimeout", ValueType.LONG, ValueType.object(STANDARD + "TimeUnit"),
            ValueType.object(STANDARD + "CompletableFuture"))) == null, "unsupported-method-no-fallback");
        int lowered = 0, monitorBodies = 0;
        for (ClassHolder cls : models) for (MethodHolder method : cls.getMethods()) {
            if (method.getProgram() == null) continue;
            boolean monitor = false, ownedCall = false;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                if (instruction instanceof MonitorEnterInstruction) monitor = true;
                if (instruction instanceof InvokeInstruction invoke && suspends.contains(invoke.getMethod())) ownedCall = true;
            }
            if (!monitor && !ownedCall) continue;
            Program loweredProgram = ProgramUtils.copy(method.getProgram());
            new CoroutineTransformation(source, suspends, true).apply(loweredProgram, method.getReference());
            require(loweredProgram.basicBlockCount() > method.getProgram().basicBlockCount(), "actual-monitor-resumption-split");
            if (monitor) monitorBodies++;
            lowered++;
        }
        require(lowered >= 15, "actual-owned-monitor-coroutine-bodies");
        ClassHolder unrelated = new ClassHolder("outside.library.CompletableFuture");
        MethodHolder identity = new MethodHolder("untouched", ValueType.VOID);
        Program program = new Program(); program.createVariable(); program.createBasicBlock().add(new ExitInstruction());
        identity.setProgram(program); unrelated.addMethod(identity);
        transform.invoke(plugin, unrelated, context);
        require(identity.getProgram() == program && program.basicBlockCount() == 1, "application-model-identity-preserved");
        System.out.println("COMPLETABLE_FUTURE_MODEL_CONTROL PASS actual-missing-class-negative;canonical-api-and-helper-identities;resolved-reference-closure;unsupported-no-fallback;actual-coroutine-monitors=" + monitorBodies + ";owned-callback-bodies=" + lowered + ";bodies=" + methods + ";application-identity");
    }
}

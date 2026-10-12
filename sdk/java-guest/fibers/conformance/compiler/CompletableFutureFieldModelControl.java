package dev.latent.guest.runtime.compiler;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Current-profile field closure control; no application or guest execution. */
public final class CompletableFutureFieldModelControl {
    private static final String STANDARD = RuntimeSubstitution.STANDARD;
    private static final String SDK = RuntimeSubstitution.SDK;
    private static final List<String> HELPERS = List.of("Action", "Aggregate", "DefaultExecutor");
    private static void require(boolean condition, String reason) {
        if (!condition) throw new AssertionError(reason);
    }
    private static FieldReader field(ClassReaderSource source, FieldReference reference) {
        return field(source, reference.getClassName(), reference.getFieldName(), new HashSet<>());
    }
    private static FieldReader field(ClassReaderSource source, String owner, String name, Set<String> visited) {
        if (!visited.add(owner)) return null;
        ClassReader model = source.get(owner);
        if (model == null) return null;
        FieldReader declared = model.getField(name);
        if (declared != null) return declared;
        for (String identity : model.getInterfaces()) {
            FieldReader inherited = field(source, identity, name, visited);
            if (inherited != null) return inherited;
        }
        return model.getParent() == null ? null : field(source, model.getParent(), name, visited);
    }
    private static boolean owned(String identity) {
        return identity.startsWith(STANDARD) && RuntimeSubstitution.API.contains(identity.substring(STANDARD.length()))
            || identity.startsWith(SDK + "CompletableFuture$")
                && HELPERS.contains(identity.substring((SDK + "CompletableFuture$").length()));
    }
    private static void canonical(ValueType type) {
        if (type instanceof ValueType.Array array) canonical(array.getItemType());
        else if (type instanceof ValueType.Object object && object.getClassName().startsWith(SDK))
            require(!RuntimeSubstitution.API.contains(object.getClassName().substring(SDK.length())),
                "field-control-no-public-SDK-type-alias:" + object.getClassName());
    }
    private static void references(ClassHolder model, ClassReaderSource source) {
        for (FieldHolder declaration : model.getFields()) canonical(declaration.getType());
        for (MethodHolder method : model.getMethods()) {
            for (ValueType type : method.getDescriptor().getSignature()) canonical(type);
            if (method.getProgram() == null) continue;
            for (BasicBlock block : method.getProgram().getBasicBlocks()) for (Instruction instruction : block) {
                FieldReference reference;
                ValueType type;
                if (instruction instanceof GetFieldInstruction read) {
                    reference = read.getField(); type = read.getFieldType();
                } else if (instruction instanceof PutFieldInstruction write) {
                    reference = write.getField(); type = write.getFieldType();
                } else continue;
                if (!owned(reference.getClassName())) continue;
                FieldReader resolved = field(source, reference);
                require(resolved != null && resolved.getType().equals(type),
                    "field-control-resolved-type:" + reference + ";declared="
                        + (resolved == null ? null : resolved.getType()) + ";instruction=" + type
                        + ";in=" + method.getReference());
                canonical(type);
            }
        }
    }
    public static void main(String[] args) throws Exception {
        var source = new ClasspathClassHolderSource(
            new ClasspathResourceProvider(CompletableFutureFieldModelControl.class.getClassLoader()),
            new ReferenceCache(), DefaultSubstituteClassNameMapping.createWithPolicies(
                List.of(new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        List<ClassHolder> models = new ArrayList<>();
        for (String name : List.of("CompletableFuture", "CompletionStage", "CompletionException")) {
            ClassHolder model = source.get(STANDARD + name);
            require(model != null, "field-control-real-model:" + name); models.add(model);
        }
        for (String name : HELPERS) {
            ClassHolder model = source.get(SDK + "CompletableFuture$" + name);
            require(model != null, "field-control-real-helper:" + name); models.add(model);
        }
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
        for (ClassHolder model : models) references(model, source);
        FieldReader inherited = field(source, new FieldReference(SDK + "CompletableFuture$Aggregate", "both"));
        require(inherited != null && inherited.getType().equals(ValueType.BOOLEAN)
            && inherited.getReference().getClassName().equals(SDK + "CompletableFuture$Action"),
            "field-control-actual-inherited-owner-and-type");
        FieldReader declared = field(source, new FieldReference(STANDARD + "CompletableFuture", "dependents"));
        require(declared != null && declared.getType().equals(ValueType.object("java.util.ArrayList")),
            "field-control-actual-declared-type");
        require(field(source, new FieldReference(SDK + "CompletableFuture$Aggregate", "absentControlField")) == null,
            "field-control-absent-field-has-no-fallback");
        System.out.println("COMPLETABLE_FUTURE_FIELD_MODEL_CONTROL PASS declared-and-inherited-types;closed-read-write-references;absent-no-fallback;models=6");
    }
}

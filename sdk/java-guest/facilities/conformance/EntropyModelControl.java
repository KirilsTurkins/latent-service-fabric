package dev.latent.guest.facilities.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

public final class EntropyModelControl {
    private static void require(boolean condition, String code) {
        if (!condition) throw new AssertionError(code);
    }
    public static void main(String[] args) {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            EntropyModelControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(
                new ClasslibSubstitutionPolicy(), new EntropySubstitution())));
        var context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder cls) { throw new AssertionError("submit"); }
        };
        String name = "java.security.SecureRandom";
        var original = source.get(name);
        require(original != null, "actual-locked-standard-model");
        var bytes = new MethodDescriptor("nextBytes", ValueType.arrayOf(ValueType.BYTE), ValueType.VOID);
        boolean originalFallback = false;
        for (var block : original.getMethod(bytes).getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call && call.getMethod().getClassName().equals("java.util.Random")
                    && call.getMethod().getName().equals("nextBytes")) originalFallback = true;
        }
        require(originalFallback, "original-c-backend-fallback-negative");
        // The actual inherited implementation determines the broker byte cost.
        // JDK Random's next(1) is not this pinned TeaVM default method.
        var nextBoolean = new MethodDescriptor("nextBoolean", ValueType.BOOLEAN);
        var random = source.get("java.util.Random");
        require(random != null && random.getMethod(nextBoolean) == null,
            "pinned-random-inherits-boolean");
        var generator = source.get("java.util.random.RandomGenerator");
        var booleanMethod = generator == null ? null : generator.getMethod(nextBoolean);
        require(booleanMethod != null && booleanMethod.getProgram() != null,
            "pinned-generator-boolean-body");
        int booleanCalls = 0;
        for (var block : booleanMethod.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call) {
                require(call.getMethod().getClassName().equals("java.util.random.RandomGenerator")
                    && call.getMethod().getDescriptor().equals(new MethodDescriptor("nextInt", ValueType.INTEGER)),
                    "pinned-boolean-delegates-to-standard-next-int");
                booleanCalls++;
            }
        }
        require(booleanCalls == 1, "pinned-boolean-consumes-one-next-int");
        var originalMethods = List.copyOf(original.getMethods());
        var originalPrograms = originalMethods.stream().map(MethodHolder::getProgram).toList();
        var template = source.get("dev.latent.guest.facilities.EntropyRandom");
        var templateMethods = List.copyOf(template.getMethods());
        var templatePrograms = templateMethods.stream().map(MethodHolder::getProgram).toList();
        var cls = ModelUtils.copyClass(original);
        var plugin = new EntropyPlugin();
        plugin.transformClass(cls, context);
        require(cls.getMethods().size() == 13, "complete-reviewed-method-set");
        require(cls.getMethod(new MethodDescriptor("next", ValueType.INTEGER, ValueType.INTEGER))
            .getModifiers().contains(ElementModifier.FINAL), "standard-next-remains-final");
        for (var method : cls.getMethods()) {
            require(method.getProgram() != null, "no-missing-standard-body");
            for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof InvokeInstruction call) {
                    require(!call.getMethod().getClassName().equals("dev.latent.guest.facilities.EntropyRandom"), "no-template-alias");
                    require(!call.getMethod().getClassName().startsWith("org.teavm.jso.crypto"), "no-browser-fallback");
                    if (call.getMethod().getClassName().equals(name))
                        require(cls.getMethod(call.getMethod().getDescriptor()) != null, "standard-method-reference-closure");
                }
            }
        }
        for (int index = 0; index < originalMethods.size(); index++)
            require(originalMethods.get(index).getProgram() == originalPrograms.get(index), "original-owner-preserved");
        for (int index = 0; index < templateMethods.size(); index++)
            require(templateMethods.get(index).getProgram() == templatePrograms.get(index), "template-owner-preserved");
        for (int mutation = 0; mutation < 3; mutation++) {
            var broken = ModelUtils.copyClass(original);
            if (mutation == 0) broken.setParent("java.lang.Object");
            if (mutation == 1) broken.removeMethod(broken.getMethod(bytes));
            if (mutation == 2) broken.getField("seedGenerator").setType(ValueType.INTEGER);
            try { plugin.transformClass(broken, context); throw new AssertionError("layout-mutation-accepted"); }
            catch (IllegalStateException expected) { }
        }
        try { plugin.transformClass(cls, context); throw new AssertionError("repeated-port-accepted"); }
        catch (IllegalStateException expected) { }
        var unrelated = new ClassHolder("outside.owner.SecureRandom");
        plugin.transformClass(unrelated, context);
        require(unrelated.getMethods().isEmpty(), "unseen-application-class-untouched");
        require(source.get("java.security.ProviderException") != null, "standard-provider-exception-identity");
        System.out.println("ENTROPY_MODEL_CONTROL PASS methods=13;original-fallback-negative;reference-closure;owners;layout-and-repeat-negatives;unseen-caller");
    }
}

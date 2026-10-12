package dev.latent.guest.runtime.compiler;

import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Test the actual locked standard enum model without application initialization. */
public final class TimeUnitModelControl {
    private static void require(boolean value, String failure) {
        if (!value) throw new AssertionError(failure);
    }
    public static void main(String[] args) {
        var loader = TimeUnitModelControl.class.getClassLoader();
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(
                new ClasslibSubstitutionPolicy(), new RuntimeSubstitution())));
        var context = new ClassHolderTransformerContext() {
            public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }
            public org.teavm.diagnostics.Diagnostics getDiagnostics() { throw new AssertionError("diagnostics"); }
            public org.teavm.cache.IncrementalDependencyRegistration getIncrementalCache() { throw new AssertionError("cache"); }
            public boolean isObfuscated() { return false; }
            public boolean isStrict() { return true; }
            public String getEntryPoint() { return "unused"; }
            public void submit(ClassHolder cls) { throw new AssertionError("submit"); }
        };
        var name = "java.util.concurrent.TimeUnit";
        var original = source.get(name);
        require(original != null && original.getField("nanoseconds") != null, "maintained-classlib-selected");
        var duration = new MethodDescriptor("convert", ValueType.object("java.time.Duration"), ValueType.LONG);
        var chrono = ValueType.object("java.time.temporal.ChronoUnit");
        var toChrono = new MethodDescriptor("toChronoUnit", chrono);
        var of = new MethodDescriptor("of", chrono, ValueType.object(name));
        require(original.getMethod(duration) == null && original.getMethod(toChrono) == null
            && original.getMethod(of) == null, "original-missing-method-negative");
        var cls = ModelUtils.copyClass(original);
        var originalMethods = List.copyOf(original.getMethods());
        var originalPrograms = originalMethods.stream().map(MethodHolder::getProgram).toList();
        var sdkTemplate = source.get("dev.latent.guest.runtime.concurrent.TimeUnit");
        var sdkMethods = List.copyOf(sdkTemplate.getMethods());
        var sdkPrograms = sdkMethods.stream().map(MethodHolder::getProgram).toList();
        var constructor = cls.getMethod(new MethodDescriptor("<init>", ValueType.object("java.lang.String"),
            ValueType.INTEGER, ValueType.LONG, ValueType.VOID));
        require(constructor != null, "maintained-enum-constructor");
        var constructorProgram = constructor.getProgram();
        var values = cls.getMethod(new MethodDescriptor("values", ValueType.arrayOf(ValueType.object(name))));
        var valuesProgram = values.getProgram();
        TimeUnitMethods.transform(cls, context);
        var nanos = new MethodDescriptor("toNanos", ValueType.LONG, ValueType.LONG);
        require(cls.getMethod(nanos).getProgram() != original.getMethod(nanos).getProgram(),
            "conversion-body-replaced-on-standard-identity");
        for (int index = 0; index < originalMethods.size(); index++) {
            var method = originalMethods.get(index);
            require(original.getMethod(method.getDescriptor()) == method
                && method.getProgram() == originalPrograms.get(index), "original-model-owner-preserved");
        }
        for (int index = 0; index < sdkMethods.size(); index++) {
            var method = sdkMethods.get(index);
            require(sdkTemplate.getMethod(method.getDescriptor()) == method
                && method.getProgram() == sdkPrograms.get(index), "sdk-template-owner-preserved");
        }
        require(cls.getMethod(duration).getProgram() != null && cls.getMethod(toChrono).getProgram() != null
            && cls.getMethod(of).getProgram() != null, "all-new-standard-methods-have-real-ir");
        require(cls.getMethod(constructor.getDescriptor()) == constructor
            && constructor.getProgram() == constructorProgram, "constructor-owner-preserved");
        require(cls.getMethod(values.getDescriptor()) == values && values.getProgram() == valuesProgram,
            "values-owner-preserved");
        for (var constant : Set.of("NANOSECONDS", "MICROSECONDS", "MILLISECONDS", "SECONDS", "MINUTES", "HOURS", "DAYS")) {
            require(cls.getField(constant) != null && cls.getField(constant).getType().equals(ValueType.object(name)),
                "enum-constant-identity");
        }
        int bodies = 0;
        for (var method : cls.getMethods()) {
            if (method.getProgram() == null) continue;
            bodies++;
            for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof GetFieldInstruction get) {
                    require(!get.getField().getClassName().equals("dev.latent.guest.runtime.concurrent.TimeUnit"), "sdk-field-alias");
                    if (get.getField().getClassName().equals(name)) require(cls.getField(get.getField().getFieldName()) != null, "resolved-standard-field");
                }
                if (instruction instanceof InvokeInstruction call) {
                    require(!call.getMethod().getClassName().equals("dev.latent.guest.runtime.concurrent.TimeUnit"), "sdk-call-alias");
                    if (call.getMethod().getClassName().equals(name)) require(cls.getMethod(call.getMethod().getDescriptor()) != null
                        || new ClassHierarchy(source).resolve("java.lang.Enum", call.getMethod().getDescriptor()) != null,
                        "resolved-standard-method:" + call.getMethod());
                }
            }
        }
        var wrongLayout = ModelUtils.copyClass(original);
        wrongLayout.getField("nanoseconds").setType(ValueType.INTEGER);
        try { TimeUnitMethods.transform(wrongLayout, context); throw new AssertionError("layout-not-rejected"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("unexpected-maintained-timeunit-layout"), "layout-error-class"); }
        var unrelated = new ClassHolder("outside.application.TimeUnit");
        TimeUnitMethods.transform(unrelated, context);
        require(unrelated.getMethods().isEmpty(), "application-class-untouched");
        System.out.println("TIMEUNIT_MODEL_CONTROL PASS missing-declarations-negative;standard-body-and-reference-closure;enum-owners-preserved;layout-negative;application-identity-preserved bodies=" + bodies);
    }
}

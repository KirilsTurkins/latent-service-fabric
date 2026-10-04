package dev.latent.guest.resources.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.ClassHolder;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Real locked class-library IR ownership control, not a guest execution test. */
public final class ImmutableResourceModelControl {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    public static void main(String[] args) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            ImmutableResourceModelControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var original = source.get("java.lang.ClassLoader");
        var descriptor = new MethodDescriptor("getResourceAsStream", ValueType.object("java.lang.String"),
            ValueType.object("java.io.InputStream"));
        require(original != null && original.getMethod(descriptor) != null, "actual-pinned-standard-class");
        var cls = ModelUtils.copyClass(original);
        var methods = List.copyOf(cls.getMethods());
        var programs = methods.stream().map(method -> method.getProgram()).toList();
        var fields = List.copyOf(cls.getFields());
        var parent = cls.getParent();
        var interfaces = List.copyOf(cls.getInterfaces());
        var originalProgram = original.getMethod(descriptor).getProgram();
        ImmutableResourcePlugin.transform(cls, null);
        require(cls.getName().equals(original.getName()) && cls.getParent().equals(parent)
            && List.copyOf(cls.getInterfaces()).equals(interfaces), "maintained-class-identity");
        require(List.copyOf(cls.getFields()).equals(fields) && List.copyOf(cls.getMethods()).equals(methods),
            "all-field-and-method-owners-preserved");
        for (int index = 0; index < methods.size(); index++) {
            var method = methods.get(index);
            require(method.getDescriptor().equals(descriptor) || method.getProgram() == programs.get(index),
                "every-unselected-method-body-preserved");
        }
        require(original.getMethod(descriptor).getProgram() == originalProgram, "source-model-owner-preserved");
        var replacement = cls.getMethod(descriptor).getProgram();
        require(replacement != originalProgram && replacement.basicBlockCount() == 1 && replacement.variableCount() == 3,
            "exact-standard-method-has-real-ir");
        int calls = 0;
        for (var block : replacement.getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call) {
                require(call.getMethod().getClassName().equals("dev.latent.guest.resources.ImmutableResources")
                    && call.getMethod().getName().equals("open"), "only-selected-immutable-lookup");
                calls++;
            }
        }
        require(calls == 1, "single-no-ambient-resource-dispatch");
        var classType = source.get("java.lang.Class");
        var classMethods = List.copyOf(classType.getMethods());
        var classPrograms = classMethods.stream().map(method -> method.getProgram()).toList();
        ImmutableResourcePlugin.transform(classType, null);
        for (int index = 0; index < classMethods.size(); index++) {
            require(classMethods.get(index).getProgram() == classPrograms.get(index), "class-relative-array-methods-preserved");
        }
        var unknown = new ClassHolder("outside.owner.ClassLoader");
        ImmutableResourcePlugin.transform(unknown, null);
        require(unknown.getMethods().isEmpty(), "unlisted-application-class-untouched");
        try {
            ImmutableResourcePlugin.transform(new ClassHolder("java.lang.ClassLoader"), null);
            throw new AssertionError("missing-method-not-rejected");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unexpected-maintained-classloader-resource-method"), "missing-method-classified");
        }
        try {
            ImmutableResourcePlugin.transform(cls, null);
            throw new AssertionError("changed-preimage-not-rejected");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unexpected-maintained-classloader-resource-preimage"), "changed-preimage-classified");
        }
        try (var first = dev.latent.guest.resources.ImmutableResources.open("outside/owner/badge.txt");
                var second = dev.latent.guest.resources.ImmutableResources.open("outside/owner/badge.txt")) {
            require(first != null && second != null && first != second, "fresh-stream-owners");
            require(first.read() == 0 && second.read() == 0 && first.read() == 255 && second.read() == 255,
                "fresh-position-and-opaque-encoding");
            require(java.util.Arrays.equals(first.readAllBytes(), new byte[]{10, 42}), "exact-remaining-bytes");
        }
        require(dev.latent.guest.resources.ImmutableResources.open("OUTSIDE/owner/badge.txt") == null
            && dev.latent.guest.resources.ImmutableResources.open("/outside/owner/badge.txt") == null
            && dev.latent.guest.resources.ImmutableResources.open("../outside/owner/badge.txt") == null
            && dev.latent.guest.resources.ImmutableResources.open("missing") == null, "case-and-absence-no-fallback");
        try {
            dev.latent.guest.resources.ImmutableResources.open(null);
            throw new AssertionError("null-not-rejected");
        } catch (NullPointerException expected) {
            require(true, "standard-null-semantics");
        }
        System.out.println("IMMUTABLE_RESOURCE_MODEL_CONTROL PASS real-pinned-IR;standard-owners-preserved;relative-array-bodies-preserved;"
            + "changed-preimage-denied;unlisted-class-untouched;exact-fresh-streams;null-and-missing;methods=" + methods.size());
    }
}

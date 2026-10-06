package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Execute against the actual locked classlib model, without app initialization. */
public final class ThrowableInitializationControl {
    private static void require(boolean value, String failure) {
        if (!value) throw new AssertionError(failure);
    }
    private static int writes(MethodHolder method) {
        int count = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof PutFieldInstruction store
                    && store.getField().equals(new FieldReference("java.lang.Throwable", "suppressed"))) count++;
        }
        return count;
    }
    private static void rejects(ClassHolder cls) {
        try { ThrowableInitialization.transform(cls); throw new AssertionError("layout-drift-accepted"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unexpected-maintained-throwable-initialization"), "closed-drift-reason");
        }
    }
    public static void main(String[] args) {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            ThrowableInitializationControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var original = source.get("java.lang.Throwable");
        require(original != null, "maintained-class-selected");
        int real = 0;
        int fake = 0;
        for (var method : original.getMethods()) {
            if (method.getName().equals("<init>")) {
                require(writes(method) == 0, "original-real-constructor-missing-initializer-negative");
                real++;
            } else if (method.getName().equals("fakeInit")) {
                require(writes(method) == 1, "original-initializer-is-in-unused-constructor");
                fake++;
            }
        }
        require(real == 5 && fake == 5, "pinned-constructor-inventory");
        var cls = ModelUtils.copyClass(original);
        var methods = List.copyOf(cls.getMethods());
        var programs = methods.stream().map(MethodHolder::getProgram).toList();
        var constructorEntries = methods.stream().map(m -> m.getProgram() == null
            ? null : m.getProgram().basicBlockAt(0).getFirstInstruction()).toList();
        ThrowableInitialization.transform(cls);
        for (int index = 0; index < methods.size(); index++) {
            var method = methods.get(index);
            require(cls.getMethod(method.getDescriptor()) == method && method.getProgram() == programs.get(index),
                "maintained-method-and-program-owner-preserved");
            if (!method.getName().equals("<init>")) {
                if (method.getProgram() != null) require(method.getProgram().basicBlockAt(0).getFirstInstruction()
                    == constructorEntries.get(index), "unrelated-maintained-method-unchanged");
                continue;
            }
            require(writes(method) == 1, "one-actual-constructor-initializer");
            var zero = method.getProgram().basicBlockAt(0).getFirstInstruction();
            require(zero instanceof IntegerConstantInstruction && ((IntegerConstantInstruction) zero).getConstant() == 0,
                "empty-array-length");
            var empty = zero.getNext();
            require(empty instanceof ConstructArrayInstruction
                && ((ConstructArrayInstruction) empty).getItemType().equals(ValueType.object("java.lang.Throwable"))
                && ((ConstructArrayInstruction) empty).getSize() == ((IntegerConstantInstruction) zero).getReceiver(),
                "actual-Throwable-array-not-SDK-alias");
            var write = empty.getNext();
            require(write instanceof PutFieldInstruction
                && ((PutFieldInstruction) write).getInstance() == method.getProgram().variableAt(0)
                && ((PutFieldInstruction) write).getValue() == ((ConstructArrayInstruction) empty).getReceiver()
                && write.getNext() == constructorEntries.get(index), "same-original-receiver-before-original-body");
        }
        var wrongField = ModelUtils.copyClass(original);
        wrongField.getField("suppressed").setType(ValueType.object("java.lang.Object"));
        rejects(wrongField);
        var missingConstructor = ModelUtils.copyClass(original);
        missingConstructor.removeMethod(missingConstructor.getMethod(new MethodDescriptor("<init>", ValueType.VOID)));
        rejects(missingConstructor);
        rejects(ModelUtils.copyClass(cls)); // A second application must not overwrite existing suppression.
        var unrelated = new ClassHolder("outside.application.Throwable");
        ThrowableInitialization.transform(unrelated);
        require(unrelated.getFields().isEmpty() && unrelated.getMethods().isEmpty(), "application-identity-unchanged");
        System.out.println("THROWABLE_INITIALIZATION_CONTROL PASS constructors=5;original-negative;real-array-initializer;method-owners;layout-and-repeated-port-negatives;application-identity");
    }
}

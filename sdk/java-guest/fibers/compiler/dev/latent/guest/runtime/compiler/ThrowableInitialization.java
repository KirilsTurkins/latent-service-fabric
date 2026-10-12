package dev.latent.guest.runtime.compiler;

import java.util.ArrayList;
import java.util.Set;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.FieldReference;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ConstructArrayInstruction;
import org.teavm.model.instructions.IntegerConstantInstruction;
import org.teavm.model.instructions.PutFieldInstruction;

/** Restore the pinned classlib's field initializer in its renamed constructors.
 * TeaVM 0.15 puts it in fakeInit, which is not the actual low-level constructor.
 * Keep the maintained Throwable class, methods, causes and application symbols.
 */
final class ThrowableInitialization {
    private static final String NAME = "java.lang.Throwable";
    private static final ValueType THROWABLE = ValueType.object(NAME);
    private static final ValueType SUPPRESSED = ValueType.arrayOf(THROWABLE);
    private static final ValueType STRING = ValueType.object("java.lang.String");
    private static final Set<MethodDescriptor> CONSTRUCTORS = Set.of(
        new MethodDescriptor("<init>", ValueType.VOID),
        new MethodDescriptor("<init>", STRING, ValueType.VOID),
        new MethodDescriptor("<init>", THROWABLE, ValueType.VOID),
        new MethodDescriptor("<init>", STRING, THROWABLE, ValueType.VOID),
        new MethodDescriptor("<init>", STRING, THROWABLE, ValueType.BOOLEAN, ValueType.BOOLEAN, ValueType.VOID));

    private ThrowableInitialization() { }

    static void transform(ClassHolder cls) {
        if (!cls.getName().equals(NAME)) return;
        var field = cls.getField("suppressed");
        if (field == null || !field.getType().equals(SUPPRESSED)
                || field.getModifiers().contains(ElementModifier.STATIC)) fail();
        var constructors = new ArrayList<MethodHolder>();
        for (var method : cls.getMethods()) {
            if (!method.getName().equals("<init>")) continue;
            var program = method.getProgram();
            if (!CONSTRUCTORS.contains(method.getDescriptor())
                    || method.getModifiers().contains(ElementModifier.STATIC)
                    || program == null || program.basicBlockCount() == 0
                    || program.basicBlockAt(0).getFirstInstruction() == null) fail();
            for (var block : program.getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof PutFieldInstruction store
                        && store.getField().equals(new FieldReference(NAME, "suppressed"))) fail();
            }
            constructors.add(method);
        }
        if (constructors.size() != CONSTRUCTORS.size()) fail();
        // Validate the entire pinned layout before changing any constructor.
        for (var method : constructors) {
            var program = method.getProgram();
            var size = program.createVariable();
            var array = program.createVariable();
            var zero = new IntegerConstantInstruction();
            zero.setConstant(0);
            zero.setReceiver(size);
            var empty = new ConstructArrayInstruction();
            empty.setItemType(THROWABLE);
            empty.setSize(size);
            empty.setReceiver(array);
            var initialize = new PutFieldInstruction();
            initialize.setInstance(program.variableAt(0));
            initialize.setField(new FieldReference(NAME, "suppressed"));
            initialize.setFieldType(SUPPRESSED);
            initialize.setValue(array);
            var first = program.basicBlockAt(0).getFirstInstruction();
            first.insertPrevious(zero);
            first.insertPrevious(empty);
            first.insertPrevious(initialize);
        }
    }

    private static void fail() {
        throw new IllegalStateException("unexpected-maintained-throwable-initialization");
    }
}

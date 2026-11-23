package org.teavm.model.optimization;

import java.lang.reflect.Field;
import java.util.List;
import java.util.Set;
import org.teavm.backend.lowlevel.transform.CoroutineTransformation;
import org.teavm.dependency.DependencyInfo;
import org.teavm.model.BasicBlock;
import org.teavm.model.ClassHierarchy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassReaderSource;
import org.teavm.model.ElementModifier;
import org.teavm.model.FieldHolder;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReader;
import org.teavm.model.MethodReference;
import org.teavm.model.MutableClassHolderSource;
import org.teavm.model.Program;
import org.teavm.model.TryCatchBlock;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.AssignInstruction;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.GetFieldInstruction;
import org.teavm.model.instructions.IntegerConstantInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.PutFieldInstruction;

/** Execute the real pinned optimizer over finite IR, without running application
 * classes or substituting these controls for signed component qualification. */
public final class FieldReadCheck implements MethodOptimizationContext {
    private static final String OWNER = "control.FieldOwner";
    private static final MethodReference AWAIT = new MethodReference("control.Await", "await", ValueType.VOID);
    private final MutableClassHolderSource source = new MutableClassHolderSource();
    private final MethodHolder method;
    private final FieldHolder field = new FieldHolder("value");
    private final Program program = new Program();
    private final Variable instance;

    private FieldReadCheck(boolean isStatic, boolean isVolatile) {
        var owner = new ClassHolder(OWNER);
        field.setType(ValueType.INTEGER);
        if (isStatic) field.getModifiers().add(ElementModifier.STATIC);
        if (isVolatile) field.getModifiers().add(ElementModifier.VOLATILE);
        owner.addField(field);
        method = new MethodHolder("read", ValueType.object(OWNER), ValueType.INTEGER);
        method.getModifiers().add(ElementModifier.STATIC);
        method.setProgram(program);
        owner.addMethod(method);
        source.putClassHolder(owner);
        program.createVariable(); // Reserved receiver slot, even for a static method.
        var parameter = program.createVariable();
        instance = isStatic ? null : parameter;
    }

    @Override public MethodReader getMethod() { return method; }
    @Override public DependencyInfo getDependencyInfo() { throw new AssertionError("unexpected-dependency-query"); }
    @Override public ClassReaderSource getClassSource() { return source; }
    @Override public ClassHierarchy getHierarchy() { return new ClassHierarchy(source); }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void jump(BasicBlock block, BasicBlock target) {
        var instruction = new JumpInstruction(); instruction.setTarget(target); block.add(instruction);
    }

    private static void exit(BasicBlock block, Variable result) {
        var instruction = new ExitInstruction(); instruction.setValueToReturn(result); block.add(instruction);
    }

    private Variable constant(BasicBlock block, int value) {
        var result = program.createVariable();
        var instruction = new IntegerConstantInstruction(); instruction.setReceiver(result);
        instruction.setConstant(value); block.add(instruction); return result;
    }

    private void put(BasicBlock block, Variable value) {
        var instruction = new PutFieldInstruction(); instruction.setField(field.getReference());
        instruction.setFieldType(ValueType.INTEGER); instruction.setInstance(instance);
        instruction.setValue(value); block.add(instruction);
    }

    private Variable get(BasicBlock block) {
        var result = program.createVariable();
        var instruction = new GetFieldInstruction(); instruction.setField(field.getReference());
        instruction.setFieldType(ValueType.INTEGER); instruction.setInstance(instance);
        instruction.setReceiver(result); block.add(instruction); return result;
    }

    private static void guard(BasicBlock block, BasicBlock handler, String type) {
        var guard = new TryCatchBlock(); guard.setExceptionType(type); guard.setHandler(handler);
        block.getTryCatchBlocks().add(guard);
    }

    private static int reads(BasicBlock block) {
        int result = 0;
        for (var instruction : block) if (instruction instanceof GetFieldInstruction) ++result;
        return result;
    }

    private static void exceptional(String mode, boolean isStatic, boolean caughtVariable, boolean lateDefinition) {
        var input = new FieldReadCheck(isStatic, false);
        var entry = input.program.createBasicBlock();
        var body = input.program.createBasicBlock();
        var normal = input.program.createBasicBlock();
        var handler = input.program.createBasicBlock();
        if (caughtVariable) handler.setExceptionVariable(input.program.createVariable());
        var value = lateDefinition ? null : input.constant(entry, 42);
        jump(entry, body);
        var call = new InvokeInstruction(); call.setType(InvocationType.SPECIAL); call.setMethod(AWAIT); body.add(call);
        if (lateDefinition) value = input.constant(body, 42);
        input.put(body, value);
        jump(body, normal);
        guard(body, handler, "java.lang.Throwable");
        exit(normal, input.get(normal));
        exit(handler, input.get(handler));
        boolean changed = new RepeatedFieldReadElimination().optimize(input, input.program);
        require(changed && reads(normal) == 0, "normal-successor-forwarding-lost");
        require(normal.getFirstInstruction() instanceof AssignInstruction, "normal-successor-not-forwarded");
        var assignment = (AssignInstruction) normal.getFirstInstruction();
        require(assignment.getAssignee() == value, "normal-successor-value-changed");
        if (mode.equals("original")) {
            require(reads(handler) == 0 && handler.getFirstInstruction() instanceof AssignInstruction,
                "original-field-cache-defect-not-observed");
            require(((AssignInstruction) handler.getFirstInstruction()).getAssignee() == value,
                "original-handler-forwarded-unexpected-value");
        } else {
            require(reads(handler) == 1, "exception-handler-reused-post-call-field-value");
        }
        // A value defined before the call is still semantically wrong in the
        // handler, even though it does not trigger the undefined-variable error.
        if (!lateDefinition) return;
        try {
            new CoroutineTransformation(input.source, Set.of(AWAIT), false).apply(input.program,
                new MethodReference(OWNER, input.method.getDescriptor()));
        } catch (AssertionError failure) {
            var origin = failure.getStackTrace()[0];
            if (!mode.equals("original") || failure.getMessage() == null
                    || !failure.getMessage().startsWith("Variable used before definition:")
                    || !origin.getClassName().equals("org.teavm.model.util.PhiUpdater")) throw failure;
            return;
        }
        require(mode.equals("corrected"), "original-coroutine-undefined-field-value-not-observed");
    }

    private static void sharedAndNestedHandlers() {
        var input = new FieldReadCheck(false, false);
        var entry = input.program.createBasicBlock();
        var first = input.program.createBasicBlock();
        var second = input.program.createBasicBlock();
        var handler = input.program.createBasicBlock();
        var outer = input.program.createBasicBlock();
        jump(entry, first);
        input.put(first, input.constant(first, 42)); jump(first, second);
        input.put(second, input.constant(second, 43)); exit(second, input.get(second));
        guard(first, handler, "java.lang.IllegalStateException");
        guard(second, handler, "java.lang.Throwable");
        handler.setExceptionVariable(input.program.createVariable());
        input.get(handler);
        input.put(handler, input.constant(handler, 44)); exit(handler, input.get(handler));
        guard(handler, outer, "java.lang.Throwable");
        outer.setExceptionVariable(input.program.createVariable()); exit(outer, input.get(outer));
        new RepeatedFieldReadElimination().optimize(input, input.program);
        require(reads(handler) == 1 && reads(outer) == 1, "nested-or-shared-handler-field-read-lost");
        require(reads(second) == 0, "nested-control-normal-forwarding-lost");
    }

    private static void normalAndReuse(String mode) throws Exception {
        var optimizer = new RepeatedFieldReadElimination();
        var input = new FieldReadCheck(false, false);
        var entry = input.program.createBasicBlock();
        input.get(entry); exit(entry, input.get(entry));
        require(optimizer.optimize(input, input.program) && reads(entry) == 1,
            "straight-line-repeated-read-not-eliminated");
        var empty = new FieldReadCheck(false, false);
        var only = empty.program.createBasicBlock(); exit(only, empty.constant(only, 0));
        boolean changed = optimizer.optimize(empty, empty.program);
        Field invalid = RepeatedFieldReadElimination.class.getDeclaredField("invalidFields");
        invalid.setAccessible(true);
        int size = ((List<?>) invalid.get(optimizer)).size();
        if (mode.equals("original")) {
            require(changed && size == 2, "original-pass-state-defect-not-observed");
        } else {
            require(!changed && size == empty.program.basicBlockCount(), "reused-pass-kept-prior-state");
        }
        var volatileInput = new FieldReadCheck(false, true);
        var block = volatileInput.program.createBasicBlock();
        volatileInput.get(block); exit(block, volatileInput.get(block));
        require(!new RepeatedFieldReadElimination().optimize(volatileInput, volatileInput.program)
            && reads(block) == 2, "volatile-field-read-eliminated");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 1 && (args[0].equals("original") || args[0].equals("corrected")), "mode");
        for (boolean isStatic : new boolean[] {false, true}) {
            for (boolean caught : new boolean[] {false, true}) {
                for (boolean late : new boolean[] {false, true}) exceptional(args[0], isStatic, caught, late);
            }
        }
        normalAndReuse(args[0]);
        if (args[0].equals("corrected")) sharedAndNestedHandlers();
        System.out.println("{\"schemaVersion\":\"latent.java.field-read-exception-control.v1\",\"mode\":\""
            + args[0] + "\",\"passed\":true}");
    }
}

package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import org.teavm.model.AccessLevel;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.BinaryInstruction;
import org.teavm.model.instructions.BinaryOperation;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.NumericOperandType;

/** Reserve once at the maintained monitor-listener allocation boundary. */
final class WaitContinuations {
    private static final String OBJECT = "java.lang.Object";
    private static final String SUPPORT = "dev.latent.guest.runtime.Monitors";
    private static final ValueType OBJECT_TYPE = ValueType.object(OBJECT);
    private static final ValueType CALLBACK = ValueType.object("org.teavm.interop.AsyncCallback");
    private WaitContinuations() { }

    private static InvokeInstruction invoke(String cls, String name, ValueType... signature) {
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL);
        call.setMethod(new MethodReference(cls, name, signature));
        return call;
    }

    static void transform(ClassHolder cls) {
        if (cls.getName().equals(OBJECT)) {
            var wait = cls.getMethod(new MethodDescriptor("wait", ValueType.LONG, ValueType.INTEGER, ValueType.VOID));
            if (wait == null || wait.getProgram() == null || wait.getProgram().basicBlockCount() == 0)
                throw new IllegalStateException("unreviewed-maintained-monitor-validation");
            var validate = invoke(SUPPORT, "validateWait", ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
            validate.setArguments(wait.getProgram().variableAt(1), wait.getProgram().variableAt(2));
            wait.getProgram().basicBlockAt(0).getFirstInstruction().insertPrevious(validate);

            var maintained = cls.getMethod(new MethodDescriptor("waitImpl", ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID));
            if (maintained == null || maintained.getProgram() == null
                    || maintained.getModifiers().contains(ElementModifier.STATIC)
                    || cls.getMethod(new MethodDescriptor("lsfOwnedWait", ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID)) != null)
                throw new IllegalStateException("unreviewed-maintained-monitor-handler");
            var raw = new MethodHolder("lsfOwnedWait", ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID);
            raw.setLevel(AccessLevel.PRIVATE);
            raw.getModifiers().add(ElementModifier.FINAL);
            raw.setProgram(maintained.getProgram());
            var instants = new HashSet<Variable>();
            for (var block : raw.getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof InvokeInstruction call
                        && call.getMethod().equals(new MethodReference("java.lang.System", "currentTimeMillis", ValueType.LONG)))
                    instants.add(call.getReceiver());
            }
            int deadlines = 0;
            for (var block : raw.getProgram().getBasicBlocks()) {
                for (var instruction = block.getFirstInstruction(); instruction != null; ) {
                    var next = instruction.getNext();
                    if (instruction instanceof BinaryInstruction sum
                            && sum.getOperation() == BinaryOperation.ADD
                            && sum.getOperandType() == NumericOperandType.LONG
                            && (instants.contains(sum.getFirstOperand()) || instants.contains(sum.getSecondOperand()))) {
                        var now = instants.contains(sum.getFirstOperand()) ? sum.getFirstOperand() : sum.getSecondOperand();
                        var call = invoke(SUPPORT, "absoluteWaitDeadline", ValueType.LONG, ValueType.LONG, ValueType.INTEGER, ValueType.LONG);
                        call.setArguments(now, raw.getProgram().variableAt(1), raw.getProgram().variableAt(2));
                        call.setReceiver(sum.getReceiver());
                        call.setLocation(sum.getLocation());
                        instruction.replace(call);
                        deadlines++;
                    }
                    instruction = next;
                }
            }
            if (instants.size() != 1 || deadlines != 1)
                throw new IllegalStateException("unreviewed-maintained-monitor-deadline");
            cls.addMethod(raw);

            var program = new Program();
            var object = program.createVariable();
            var millis = program.createVariable();
            var nanos = program.createVariable();
            var callback = program.createVariable();
            var call = invoke(SUPPORT, "ownedWait", OBJECT_TYPE, ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID);
            call.setArguments(object, millis, nanos, callback);
            var block = program.createBasicBlock();
            block.add(call);
            block.add(new ExitInstruction());
            maintained.setProgram(program);
        } else if (cls.getName().equals(SUPPORT)) {
            var method = cls.getMethod(new MethodDescriptor("rawWait", OBJECT_TYPE, ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID));
            if (method == null) throw new IllegalStateException("missing-owned-monitor-hook");
            var program = new Program();
            program.createVariable();
            var object = program.createVariable();
            var millis = program.createVariable();
            var nanos = program.createVariable();
            var callback = program.createVariable();
            var call = invoke(OBJECT, "lsfOwnedWait", ValueType.LONG, ValueType.INTEGER, CALLBACK, ValueType.VOID);
            call.setInstance(object);
            call.setArguments(millis, nanos, callback);
            var block = program.createBasicBlock();
            block.add(call);
            block.add(new ExitInstruction());
            method.setProgram(program);
        }
    }
}

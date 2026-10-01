package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import org.teavm.model.AccessLevel;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.FieldReference;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.BinaryInstruction;
import org.teavm.model.instructions.BinaryOperation;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.GetFieldInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.NumericOperandType;

/** Keep the maintained low-level handler, with bounded owned sleep lifetimes. */
final class SleepContinuations {
    private static final String THREAD = "java.lang.Thread";
    private static final String SUPPORT = "dev.latent.guest.runtime.Monitors";
    private static final ValueType CALLBACK = ValueType.object("org.teavm.interop.AsyncCallback");
    private SleepContinuations() { }

    private static void delegate(MethodHolder method, String cls, String name, ValueType... signature) {
        var program = new Program();
        program.createVariable();
        var arguments = new Variable[signature.length - 1];
        for (int index = 0; index < arguments.length; index++) arguments[index] = program.createVariable();
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL);
        call.setMethod(new MethodReference(cls, name, signature));
        call.setArguments(arguments);
        var block = program.createBasicBlock();
        block.add(call);
        block.add(new ExitInstruction());
        method.setProgram(program);
    }

    static void transform(ClassHolder cls) {
        if (cls.getName().equals(THREAD)) {
            var descriptor = new MethodDescriptor("sleep", ValueType.LONG, CALLBACK, ValueType.VOID);
            var maintained = cls.getMethod(descriptor);
            if (maintained == null || maintained.getProgram() == null
                    || !maintained.getModifiers().contains(ElementModifier.STATIC)
                    || cls.getMethod(new MethodDescriptor("lsfOwnedSleep", ValueType.LONG, CALLBACK, ValueType.VOID)) != null)
                throw new IllegalStateException("unreviewed-maintained-sleep-handler");
            var raw = new MethodHolder("lsfOwnedSleep", ValueType.LONG, CALLBACK, ValueType.VOID);
            raw.setLevel(AccessLevel.PRIVATE);
            raw.getModifiers().add(ElementModifier.STATIC);
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
                        var call = new InvokeInstruction();
                        call.setType(InvocationType.SPECIAL);
                        call.setMethod(new MethodReference(SUPPORT, "absoluteSleepDeadline", ValueType.LONG, ValueType.LONG, ValueType.LONG));
                        call.setArguments(now, raw.getProgram().variableAt(1));
                        call.setReceiver(sum.getReceiver());
                        call.setLocation(sum.getLocation());
                        instruction.replace(call);
                        deadlines++;
                    }
                    instruction = next;
                }
            }
            if (instants.size() != 1 || deadlines != 1)
                throw new IllegalStateException("unreviewed-maintained-sleep-deadline");
            cls.addMethod(raw);
            delegate(maintained, SUPPORT, "ownedSleep", ValueType.LONG, CALLBACK, ValueType.VOID);

            var nanos = new MethodDescriptor("sleep", ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
            if (cls.getMethod(nanos) != null) throw new IllegalStateException("unreviewed-maintained-sleep-nanos");
            var method = new MethodHolder(nanos);
            method.setLevel(AccessLevel.PUBLIC);
            method.getModifiers().add(ElementModifier.STATIC);
            delegate(method, SUPPORT, "sleepNanos", ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
            cls.addMethod(method);
        } else if (cls.getName().equals(THREAD + "$SleepHandler")) {
            var threadType = ValueType.object(THREAD);
            if (cls.getField("thread") == null || !cls.getField("thread").getType().equals(threadType)
                    || cls.getField("callback") == null || !cls.getField("callback").getType().equals(CALLBACK))
                throw new IllegalStateException("unreviewed-maintained-sleep-fields");
            int interrupted = 0;
            for (var method : cls.getMethods()) {
                if (!method.getName().startsWith("lambda$interrupted$")) continue;
                if (method.parameterCount() != 0 || method.getModifiers().contains(ElementModifier.STATIC))
                    throw new IllegalStateException("unreviewed-maintained-sleep-interruption");
                var program = new Program();
                var self = program.createVariable();
                var thread = program.createVariable();
                var callback = program.createVariable();
                var block = program.createBasicBlock();
                var getThread = new GetFieldInstruction();
                getThread.setInstance(self);
                getThread.setField(new FieldReference(cls.getName(), "thread"));
                getThread.setFieldType(threadType);
                getThread.setReceiver(thread);
                block.add(getThread);
                var getCallback = new GetFieldInstruction();
                getCallback.setInstance(self);
                getCallback.setField(new FieldReference(cls.getName(), "callback"));
                getCallback.setFieldType(CALLBACK);
                getCallback.setReceiver(callback);
                block.add(getCallback);
                var call = new InvokeInstruction();
                call.setType(InvocationType.SPECIAL);
                call.setMethod(new MethodReference(SUPPORT, "interruptedSleep", threadType, CALLBACK, ValueType.VOID));
                call.setArguments(thread, callback);
                block.add(call);
                block.add(new ExitInstruction());
                method.setProgram(program);
                interrupted++;
            }
            if (interrupted != 2) throw new IllegalStateException("unreviewed-maintained-sleep-callbacks");
        } else if (cls.getName().equals(SUPPORT)) {
            var method = cls.getMethod(new MethodDescriptor("rawSleep", ValueType.LONG, CALLBACK, ValueType.VOID));
            if (method == null) throw new IllegalStateException("missing-owned-sleep-hook");
            delegate(method, THREAD, "lsfOwnedSleep", ValueType.LONG, CALLBACK, ValueType.VOID);
        }
    }
}

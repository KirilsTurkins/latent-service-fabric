package dev.latent.guest.runtime.compiler;

import java.util.HashSet;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.FieldReference;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.GetFieldInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.NullConstantInstruction;
import org.teavm.model.instructions.PutFieldInstruction;

/** Exact TeaVM 0.15 monitor fixes, before dependency/continuation analysis. */
final class MonitorContinuations {
    private static final String SUPPORT = "dev.latent.guest.runtime.Monitors";
    private static final String FIBER = "org.teavm.runtime.Fiber";
    private static final ValueType OBJECT = ValueType.object("java.lang.Object");
    private static final ValueType THREAD = ValueType.object("java.lang.Thread");
    private static final ValueType CALLBACK = ValueType.object("org.teavm.interop.AsyncCallback");
    private MonitorContinuations() { }

    private static InvokeInstruction invoke(String cls, String name, ValueType... signature) {
        var instruction = new InvokeInstruction();
        instruction.setType(InvocationType.SPECIAL);
        instruction.setMethod(new MethodReference(cls, name, signature));
        return instruction;
    }

    private static void delegate(MethodHolder method, String cls, String name, ValueType... signature) {
        var program = new Program();
        program.createVariable(); // Static receiver slot precedes parameters.
        var call = invoke(cls, name, signature);
        var arguments = new Variable[signature.length - 1];
        for (int index = 0; index < arguments.length; index++) arguments[index] = program.createVariable();
        call.setArguments(arguments);
        var block = program.createBasicBlock();
        block.add(call);
        block.add(new ExitInstruction());
        method.setProgram(program);
    }

    private static Variable field(ClassHolder cls, Program program, String name, ValueType type) {
        var declaration = cls.getField(name);
        if (declaration == null || !declaration.getType().equals(type))
            throw new IllegalStateException("unreviewed-maintained-monitor-field-" + name);
        var result = program.createVariable();
        var get = new GetFieldInstruction();
        get.setInstance(program.variableAt(0));
        get.setField(new FieldReference(cls.getName(), name));
        get.setFieldType(type);
        get.setReceiver(result);
        program.basicBlockAt(0).add(get);
        return result;
    }

    private static void clearCompletion(MethodHolder method, String written, String cleared, ValueType type) {
        var program = method.getProgram();
        if (program == null) throw new IllegalStateException("unreviewed-maintained-fiber-callback");
        int changed = 0;
        for (var block : program.getBasicBlocks()) for (var instruction : block) {
            if (!(instruction instanceof PutFieldInstruction store)
                    || !store.getField().getClassName().equals(FIBER)
                    || !store.getField().getFieldName().equals(written)) continue;
            var empty = program.createVariable();
            var value = new NullConstantInstruction();
            value.setReceiver(empty);
            var clear = new PutFieldInstruction();
            clear.setInstance(store.getInstance());
            clear.setField(new FieldReference(FIBER, cleared));
            clear.setFieldType(type);
            clear.setValue(empty);
            instruction.insertPrevious(value);
            instruction.insertPrevious(clear);
            changed++;
        }
        if (changed != 2) throw new IllegalStateException("unreviewed-maintained-fiber-completion");
    }

    static void transform(ClassHolder cls) {
        if (cls.getName().equals(SUPPORT)) {
            for (var method : cls.getMethods()) {
                if (method.getName().equals("restore"))
                    delegate(method, "java.lang.Thread", "setCurrentThread", THREAD, ValueType.VOID);
                else if (method.getName().equals("reacquire"))
                    delegate(method, "java.lang.Object", "monitorEnterWait", OBJECT, ValueType.INTEGER, CALLBACK, ValueType.VOID);
            }
        } else if (cls.getName().equals(FIBER + "$AsyncCallbackImpl")) {
            // The pinned compiler keeps both fields across multiple suspensions.
            // A successful callback must replace an earlier asynchronous failure,
            // and a failed callback must release the previous successful result.
            for (var method : cls.getMethods()) {
                if (method.getName().equals("complete") && method.parameterCount() == 1)
                    clearCompletion(method, "result", "exception", ValueType.object("java.lang.Throwable"));
                else if (method.getName().equals("error") && method.parameterCount() == 1)
                    clearCompletion(method, "exception", "result", OBJECT);
            }
        } else if (cls.getName().equals("java.lang.Object$NotifyListenerImpl")) {
            for (var method : cls.getMethods()) {
                if (!method.getName().startsWith("lambda$interrupted$")) continue;
                if (method.parameterCount() != 0 || method.getModifiers().contains(ElementModifier.STATIC))
                    throw new IllegalStateException("unreviewed-maintained-monitor-interruption");
                var program = new Program();
                program.createVariable();
                program.createBasicBlock();
                var object = field(cls, program, "obj", OBJECT);
                var count = field(cls, program, "lockCount", ValueType.INTEGER);
                var thread = field(cls, program, "currentThread", THREAD);
                var callback = field(cls, program, "callback", CALLBACK);
                var call = invoke(SUPPORT, "interruptedWait", OBJECT, ValueType.INTEGER, THREAD, CALLBACK, ValueType.VOID);
                call.setArguments(object, count, thread, callback);
                program.basicBlockAt(0).add(call);
                program.basicBlockAt(0).add(new ExitInstruction());
                method.setProgram(program);
            }
        } else if (cls.getName().equals("java.lang.Object")) {
            for (var method : cls.getMethods()) {
                var program = method.getProgram();
                if (program == null) continue;
                if (method.getName().equals("wait")) {
                    for (var block : program.getBasicBlocks()) for (var instruction : block) {
                        if (instruction instanceof InvokeInstruction call
                                && call.getMethod().getClassName().equals("java.lang.Object")
                                && call.getMethod().getName().equals("waitImpl"))
                            instruction.insertPrevious(invoke(SUPPORT, "beforeWait", ValueType.VOID));
                    }
                } else if (method.getName().equals("waitForOtherThreads")) {
                    var nulls = new HashSet<Variable>();
                    for (var block : program.getBasicBlocks()) for (var instruction : block)
                        if (instruction instanceof NullConstantInstruction value) nulls.add(value.getReceiver());
                    int removed = 0;
                    for (var block : program.getBasicBlocks()) {
                        for (var instruction = block.getFirstInstruction(); instruction != null; ) {
                            var next = instruction.getNext();
                            if (instruction instanceof PutFieldInstruction store
                                    && store.getField().getClassName().equals("java.lang.Object$Monitor")
                                    && store.getField().getFieldName().equals("enteringThreads")
                                    && nulls.contains(store.getValue())) {
                                instruction.delete();
                                removed++;
                            }
                            instruction = next;
                        }
                    }
                    if (removed != 1) throw new IllegalStateException("unreviewed-maintained-monitor-entry-queue");
                }
            }
        }
    }
}

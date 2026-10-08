package dev.latent.guest.runtime.compiler;

import java.util.ArrayList;
import org.teavm.model.BasicBlock;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodHolder;
import org.teavm.model.TryCatchBlock;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ClassConstantInstruction;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.MonitorEnterInstruction;
import org.teavm.model.instructions.MonitorExitInstruction;
import org.teavm.model.instructions.RaiseInstruction;

/** The maintained C backend handles monitor instructions, but does not emit
 * method-level locking from ACC_SYNCHRONIZED. Preserve those standard semantics
 * in IR before dependency/continuation analysis, without changing source/JARs. */
final class SynchronizedMethods {
    private SynchronizedMethods() { }

    static void lower(String className, MethodHolder method) {
        if (!method.getModifiers().contains(ElementModifier.SYNCHRONIZED)) return;
        var program = method.getProgram();
        if (program == null || program.basicBlockCount() == 0) return;
        var body = new ArrayList<BasicBlock>();
        for (var block : program.getBasicBlocks()) body.add(block);
        var entry = program.createBasicBlock();
        var order = new ArrayList<BasicBlock>();
        order.add(entry);
        order.addAll(body);
        program.pack();
        program.rearrangeBasicBlocks(order);

        var monitor = program.variableAt(0);
        if (method.getModifiers().contains(ElementModifier.STATIC)) {
            monitor = program.createVariable();
            var constant = new ClassConstantInstruction();
            constant.setConstant(ValueType.object(className));
            constant.setReceiver(monitor);
            entry.add(constant);
        }
        var enter = new MonitorEnterInstruction();
        enter.setObjectRef(monitor);
        entry.add(enter);
        var jump = new JumpInstruction();
        jump.setTarget(body.get(0));
        entry.add(jump);

        // Acquisition is outside the protected body. Every escaping exception,
        // including one from a user's existing catch/finally block, releases
        // the exact same monitor before propagating the original throwable.
        var cleanup = program.createBasicBlock();
        var exception = program.createVariable();
        cleanup.setExceptionVariable(exception);
        var release = new MonitorExitInstruction();
        release.setObjectRef(monitor);
        cleanup.add(release);
        var propagate = new RaiseInstruction();
        propagate.setException(exception);
        cleanup.add(propagate);
        for (var block : body) {
            var handler = new TryCatchBlock();
            handler.setHandler(cleanup);
            block.getTryCatchBlocks().add(handler);
            for (var instruction : block) {
                if (instruction instanceof ExitInstruction) {
                    var leave = new MonitorExitInstruction();
                    leave.setObjectRef(monitor);
                    instruction.insertPrevious(leave);
                }
            }
        }
        method.getModifiers().remove(ElementModifier.SYNCHRONIZED);
        program.pack();
    }
}

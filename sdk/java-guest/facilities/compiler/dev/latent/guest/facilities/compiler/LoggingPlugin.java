package dev.latent.guest.facilities.compiler;

import org.teavm.model.*;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Keep the pinned standard streams and redirect their sole console operation. */
public final class LoggingPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String PREFIX = "org.teavm.classlib.impl.console.";
    private static final MethodDescriptor WRITE = new MethodDescriptor("write",
        ValueType.arrayOf(ValueType.BYTE), ValueType.INTEGER, ValueType.INTEGER, ValueType.VOID);
    @Override public void install(TeaVMHost host) { host.add(this); }
    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        boolean stdout = cls.getName().equals(PREFIX + "StdoutOutputStream");
        if (!stdout && !cls.getName().equals(PREFIX + "StderrOutputStream")) return;
        var singleton = cls.getField("INSTANCE");
        var method = cls.getMethod(WRITE);
        if (!cls.getParent().equals(PREFIX + "ConsoleOutputStream") || cls.getMethods().size() != 3
                || cls.getFields().size() != 1 || singleton == null
                || !singleton.getType().equals(ValueType.object(cls.getName()))
                || !singleton.getModifiers().contains(ElementModifier.STATIC)
                || !singleton.getModifiers().contains(ElementModifier.FINAL)
                || method == null || method.getProgram() == null
                || method.getModifiers().contains(ElementModifier.STATIC)) throw changed();
        var program = ModelUtils.copyMethod(method).getProgram();
        int calls = 0;
        for (var block : program.getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call) {
                var expected = new MethodReference(PREFIX + "Console",
                    new MethodDescriptor(stdout ? "writeStdout" : "writeStderr", WRITE.getSignature()));
                if (!call.getMethod().equals(expected) || call.getInstance() != null
                        || call.getArguments().size() != 3 || call.getReceiver() != null) throw changed();
                call.setMethod(new MethodReference("dev.latent.guest.facilities.StandardLog",
                    new MethodDescriptor(stdout ? "writeOut" : "writeErr", WRITE.getSignature())));
                calls++;
            }
        }
        if (calls != 1) throw changed();
        method.setProgram(program);
    }
    private static IllegalStateException changed() {
        return new IllegalStateException("unreviewed-maintained-standard-console-layout");
    }
}

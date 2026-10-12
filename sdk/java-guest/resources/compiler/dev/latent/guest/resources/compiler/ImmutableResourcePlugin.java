package dev.latent.guest.resources.compiler;

import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Replace one backend-specific method, retaining the maintained class owner.
 * The SDK compiler lock binds the exact original TeaVM class-library JAR.
 * Every selected resource is verified before its literal source is generated.
 */
public final class ImmutableResourcePlugin implements TeaVMPlugin {
    @Override public void install(TeaVMHost host) {
        host.add(ImmutableResourcePlugin::transform);
    }

    public static void transform(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals("java.lang.ClassLoader")) return;
        var descriptor = new MethodDescriptor("getResourceAsStream", ValueType.object("java.lang.String"),
            ValueType.object("java.io.InputStream"));
        var method = cls.getMethod(descriptor);
        if (method == null || method.getProgram() == null) {
            throw new IllegalStateException("unexpected-maintained-classloader-resource-method");
        }
        boolean supply = false;
        boolean string = false;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call
                    && call.getMethod().getClassName().equals(cls.getName())) {
                supply |= call.getMethod().getName().equals("supplyResources");
                string |= call.getMethod().getName().equals("resourceToString");
            }
        }
        if (!supply || !string) {
            throw new IllegalStateException("unexpected-maintained-classloader-resource-preimage");
        }
        var program = new Program();
        program.createVariable(); // Preserve the instance receiver slot.
        var name = program.createVariable();
        var result = program.createVariable();
        var block = program.createBasicBlock();
        var open = new InvokeInstruction();
        open.setType(InvocationType.SPECIAL);
        open.setMethod(new MethodReference("dev.latent.guest.resources.ImmutableResources", "open",
            ValueType.object("java.lang.String"), ValueType.object("java.io.InputStream")));
        open.setArguments(name);
        open.setReceiver(result);
        block.add(open);
        var exit = new ExitInstruction();
        exit.setValueToReturn(result);
        block.add(exit);
        method.setProgram(program);
    }
}

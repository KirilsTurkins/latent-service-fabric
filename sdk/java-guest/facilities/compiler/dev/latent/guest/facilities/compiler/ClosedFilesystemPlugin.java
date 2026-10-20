package dev.latent.guest.facilities.compiler;

import java.util.List;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Closed WASI target metadata and catchable refusal beneath unchanged java.io. */
public final class ClosedFilesystemPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String OWNER = "org.teavm.backend.c.runtime.fs.CFileSystem";
    private static final MethodDescriptor USER = new MethodDescriptor("getUserDir", ValueType.object("java.lang.String"));
    private static final MethodDescriptor FILE = new MethodDescriptor("getFile", ValueType.object("java.lang.String"),
        ValueType.object("org.teavm.runtime.fs.VirtualFile"));
    private static final MethodDescriptor WINDOWS = new MethodDescriptor("isWindows", ValueType.BOOLEAN);

    @Override public void install(TeaVMHost host) { host.add(this); }

    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals(OWNER)) return;
        if (!cls.getParent().equals("java.lang.Object") || cls.getMethods().size() != 34
                || !List.copyOf(cls.getInterfaces()).equals(List.of("org.teavm.runtime.fs.VirtualFileSystem"))
                || cls.getFields().size() != 2 || cls.getField("cache") == null
                || !cls.getField("cache").getType().equals(ValueType.object("java.util.Map"))
                || cls.getField("referenceQueue") == null
                || !cls.getField("referenceQueue").getType().equals(ValueType.object("java.lang.ref.ReferenceQueue")))
            throw changed();
        // Validate every selected original before publishing any new body. The
        // captured compiler lock authenticates the complete original core JAR.
        checked(cls, USER, new MethodReference(OWNER, "workDirectory",
            ValueType.object("org.teavm.interop.Address"), ValueType.INTEGER));
        checked(cls, FILE, new MethodReference(OWNER, "getByPath", ValueType.object("java.lang.String"),
            ValueType.object("org.teavm.backend.c.runtime.fs.CVirtualFile")));
        checked(cls, WINDOWS, new MethodReference(OWNER, "isWindowsNative", ValueType.BOOLEAN));
        cls.getMethod(USER).setProgram(unsupported(0));
        cls.getMethod(FILE).setProgram(unsupported(1));
        var program = new Program();
        program.createVariable();
        var result = program.createVariable();
        var block = program.createBasicBlock();
        var constant = new IntegerConstantInstruction();
        constant.setReceiver(result);
        constant.setConstant(0); // The maintained WASI target has POSIX path syntax.
        block.add(constant);
        var exit = new ExitInstruction();
        exit.setValueToReturn(result);
        block.add(exit);
        cls.getMethod(WINDOWS).setProgram(program);
    }

    private static void checked(ClassHolder cls, MethodDescriptor descriptor, MethodReference expected) {
        var method = cls.getMethod(descriptor);
        if (method == null || method.getProgram() == null || method.getModifiers().contains(ElementModifier.STATIC)
                || method.getModifiers().contains(ElementModifier.NATIVE)) throw changed();
        int nativeBoundary = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction call && call.getMethod().getClassName().equals(OWNER)) {
                if (!call.getMethod().equals(expected)) throw changed();
                nativeBoundary++;
            }
        }
        if (nativeBoundary != 1) throw changed();
    }

    private static Program unsupported(int parameters) {
        var program = new Program();
        for (int i = 0; i <= parameters; i++) program.createVariable();
        var exception = program.createVariable();
        var block = program.createBasicBlock();
        var create = new ConstructInstruction();
        create.setType("java.lang.UnsupportedOperationException");
        create.setReceiver(exception);
        block.add(create);
        var initialize = new InvokeInstruction();
        initialize.setType(InvocationType.SPECIAL);
        initialize.setMethod(new MethodReference("java.lang.UnsupportedOperationException", "<init>", ValueType.VOID));
        initialize.setInstance(exception);
        block.add(initialize);
        var raise = new RaiseInstruction();
        raise.setException(exception);
        block.add(raise);
        return program;
    }

    private static IllegalStateException changed() {
        return new IllegalStateException("unreviewed-maintained-closed-filesystem-layout");
    }
}

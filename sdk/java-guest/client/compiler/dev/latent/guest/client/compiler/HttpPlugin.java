package dev.latent.guest.client.compiler;

import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformer;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.AccessLevel;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.ConstructInstruction;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Source-bound replacement of the maintained URL's default browser handler. */
public final class HttpPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String ORIGINAL = "java.net.impl.XHRStreamHandler";
    private static final String REPLACEMENT = "dev.latent.guest.client.StreamHandler";
    @Override public void install(TeaVMHost host) { host.add(this); }
    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        if (cls.getName().equals("java.net.URLConnection")) {
            bridge(cls, "getContentLengthLong", "contentLength", ValueType.LONG);
            bridge(cls, "getHeaderFieldLong", "headerLong", ValueType.object("java.lang.String"),
                ValueType.LONG, ValueType.LONG);
            return;
        }
        if (cls.getName().equals("java.net.HttpURLConnection")) {
            bridge(cls, "setFixedLengthStreamingMode", "fixedLength", ValueType.LONG, ValueType.VOID);
            var proxy = new MethodHolder("usingProxy", ValueType.BOOLEAN);
            if (cls.getMethod(proxy.getDescriptor()) != null) throw changed();
            proxy.setLevel(AccessLevel.PUBLIC);
            proxy.getModifiers().add(ElementModifier.ABSTRACT);
            cls.addMethod(proxy);
            return;
        }
        if (!cls.getName().equals("java.net.URL")) return;
        var setup = cls.getMethod(new MethodDescriptor("setupStreamHandler", ValueType.VOID));
        if (setup == null || setup.getProgram() == null) throw changed();
        int constructs = 0, constructors = 0;
        for (var block : setup.getProgram().getBasicBlocks()) {
            for (var instruction : block) {
                if (instruction instanceof ConstructInstruction value && value.getType().equals(ORIGINAL)) constructs++;
                if (instruction instanceof InvokeInstruction value
                        && value.getMethod().equals(new MethodReference(ORIGINAL, "<init>", ValueType.VOID))) constructors++;
            }
        }
        if (constructs != 1 || constructors != 1) throw changed();
        int[] references = {0};
        ClassHolder renamed = new ClassRefsRenamer(new ReferenceCache(), name -> {
            if (!name.equals(ORIGINAL)) return name;
            references[0]++;
            return REPLACEMENT;
        }).rename(cls);
        if (renamed != cls || references[0] == 0) {
            throw changed();
        }
    }

    private static IllegalStateException changed() {
        return new IllegalStateException("pinned standard HTTP class-library shape changed");
    }

    /** Add only missing standard members, backed by concrete bounded operations. */
    private static void bridge(ClassHolder cls, String name, String helper, ValueType... signature) {
        var method = new MethodHolder(name, signature);
        if (cls.getMethod(method.getDescriptor()) != null) throw changed();
        method.setLevel(AccessLevel.PUBLIC);
        var program = new Program();
        var arguments = new Variable[signature.length];
        var staticSignature = new ValueType[signature.length + 1];
        arguments[0] = program.createVariable();
        staticSignature[0] = ValueType.object(cls.getName());
        for (int index = 0; index < signature.length - 1; index++) {
            arguments[index + 1] = program.createVariable();
            staticSignature[index + 1] = signature[index];
        }
        staticSignature[signature.length] = signature[signature.length - 1];
        var block = program.createBasicBlock();
        var invoke = new InvokeInstruction();
        invoke.setType(InvocationType.SPECIAL);
        invoke.setMethod(new MethodReference("dev.latent.guest.client.StandardMembers", helper, staticSignature));
        invoke.setArguments(arguments);
        var exit = new ExitInstruction();
        if (signature[signature.length - 1] != ValueType.VOID) {
            var value = program.createVariable();
            invoke.setReceiver(value);
            exit.setValueToReturn(value);
        }
        block.add(invoke);
        block.add(exit);
        method.setProgram(program);
        cls.addMethod(method);
    }
}

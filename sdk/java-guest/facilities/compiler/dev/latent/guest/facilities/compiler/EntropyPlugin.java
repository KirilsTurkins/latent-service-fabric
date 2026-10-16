package dev.latent.guest.facilities.compiler;

import java.util.List;
import org.teavm.model.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** Replace only the actual pinned standard class, independently of callers. */
public final class EntropyPlugin implements TeaVMPlugin, ClassHolderTransformer {
    private static final String STANDARD = "java.security.SecureRandom";
    private static final String TEMPLATE = "dev.latent.guest.facilities.EntropyRandom";
    private static final ValueType BYTES = ValueType.arrayOf(ValueType.BYTE);
    private static final List<MethodDescriptor> ORIGINAL = List.of(
        new MethodDescriptor("<init>", ValueType.VOID),
        new MethodDescriptor("<init>", BYTES, ValueType.VOID),
        new MethodDescriptor("getInstance", ValueType.object("java.lang.String"), ValueType.object(STANDARD)),
        new MethodDescriptor("getAlgorithm", ValueType.object("java.lang.String")),
        new MethodDescriptor("setSeed", BYTES, ValueType.VOID),
        new MethodDescriptor("reseed", ValueType.VOID),
        new MethodDescriptor("next", ValueType.INTEGER, ValueType.INTEGER),
        new MethodDescriptor("nextBytes", BYTES, ValueType.VOID),
        new MethodDescriptor("nextInt", ValueType.INTEGER),
        new MethodDescriptor("nextDouble", ValueType.DOUBLE),
        new MethodDescriptor("getSeed", ValueType.INTEGER, BYTES),
        new MethodDescriptor("generateSeed", ValueType.INTEGER, BYTES)
    );
    @Override public void install(TeaVMHost host) { host.add(this); }
    @Override public void transformClass(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals(STANDARD)) return;
        if (!cls.getParent().equals("java.util.Random") || cls.getMethods().size() != ORIGINAL.size()
                || ORIGINAL.stream().anyMatch(method -> cls.getMethod(method) == null)) throw changed();
        var field = cls.getField("seedGenerator");
        if (cls.getFields().size() != 1 || field == null || !field.getType().equals(ValueType.object(STANDARD))
                || !field.getModifiers().contains(ElementModifier.STATIC)) throw changed();
        var source = context.getHierarchy().getClassSource().get(TEMPLATE);
        if (source == null) throw changed();
        var template = new ClassRefsRenamer(new ReferenceCache(), name ->
            name.equals(TEMPLATE) ? STANDARD : name).rename(ModelUtils.copyClass(source));
        var signatures = new java.util.ArrayList<>(ORIGINAL);
        signatures.add(new MethodDescriptor("setSeed", ValueType.LONG, ValueType.VOID));
        var replacements = new java.util.ArrayList<MethodHolder>();
        for (var signature : signatures) {
            var method = template.getMethod(signature);
            if (method == null || method.getProgram() == null) throw changed();
            replacements.add(ModelUtils.copyMethod(method));
        }
        for (var method : replacements) {
            var previous = cls.getMethod(method.getDescriptor());
            if (previous != null) cls.removeMethod(previous);
            cls.addMethod(method);
        }
    }
    private static IllegalStateException changed() {
        return new IllegalStateException("unreviewed-maintained-securerandom-layout");
    }
}

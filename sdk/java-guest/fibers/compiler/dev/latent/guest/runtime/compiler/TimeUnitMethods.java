package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.model.AccessLevel;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClassRefsRenamer;

/** Port the reviewed methods onto the classlib's actual, single enum identity. */
final class TimeUnitMethods {
    private static final String STANDARD = "java.util.concurrent.TimeUnit";
    private static final String SDK = "dev.latent.guest.runtime.concurrent.TimeUnit";
    private static final ValueType UNIT = ValueType.object(STANDARD);
    private static final ValueType CHRONO = ValueType.object("java.time.temporal.ChronoUnit");
    private static final List<MethodDescriptor> METHODS = List.of(
        new MethodDescriptor("convert", ValueType.LONG, UNIT, ValueType.LONG),
        new MethodDescriptor("convert", ValueType.object("java.time.Duration"), ValueType.LONG),
        new MethodDescriptor("toChronoUnit", CHRONO),
        new MethodDescriptor("of", CHRONO, UNIT),
        new MethodDescriptor("toNanos", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toMicros", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toMillis", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toSeconds", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toMinutes", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toHours", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("toDays", ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("timedWait", ValueType.object("java.lang.Object"), ValueType.LONG, ValueType.VOID),
        new MethodDescriptor("timedJoin", ValueType.object("java.lang.Thread"), ValueType.LONG, ValueType.VOID),
        new MethodDescriptor("sleep", ValueType.LONG, ValueType.VOID),
        new MethodDescriptor("convertScale", ValueType.LONG, ValueType.LONG, ValueType.LONG, ValueType.LONG),
        new MethodDescriptor("excessNanos", ValueType.LONG, ValueType.LONG, ValueType.INTEGER)
    );

    private TimeUnitMethods() { }

    static void transform(ClassHolder cls, ClassHolderTransformerContext context) {
        if (!cls.getName().equals(STANDARD)) return;
        // TeaVM's classlib substitution precedes the SDK SPI policy when both
        // supply TimeUnit. Adding an SDK enum alone does not replace its body.
        // Preserve the maintained enum constants, constructor and values API.
        var scale = cls.getField("nanoseconds");
        if (scale == null || !scale.getType().equals(ValueType.LONG)
                || scale.getModifiers().contains(ElementModifier.STATIC)
                || scale.getLevel() != AccessLevel.PRIVATE
                || !cls.getParent().equals("java.lang.Enum")) {
            throw new IllegalStateException("unexpected-maintained-timeunit-layout");
        }
        var source = context.getHierarchy().getClassSource().get(SDK);
        if (source == null) throw new IllegalStateException("missing-sdk-timeunit-body");
        // Copy before renaming: the class source and its program owners remain
        // intact. Only these SDK-owned method bodies are installed afterward.
        var template = new ClassRefsRenamer(new ReferenceCache(), name ->
            name.equals(SDK) ? STANDARD : name).rename(ModelUtils.copyClass(source));
        for (var descriptor : METHODS) {
            var method = template.getMethod(descriptor);
            if (method == null || method.getProgram() == null) {
                throw new IllegalStateException("missing-sdk-timeunit-method");
            }
            var old = cls.getMethod(descriptor);
            if (old != null) cls.removeMethod(old);
            cls.addMethod(ModelUtils.copyMethod(method));
        }
    }
}

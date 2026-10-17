package dev.latent.guest.runtime.compiler;

import java.util.ArrayList;
import java.util.Set;
import org.teavm.model.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClassRefsRenamer;

/** Replace the pinned classlib timer bodies on their single standard identity. */
final class StandardTimerMethods {
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("unexpected-maintained-standard-timer-layout");
    }
    static void transform(ClassHolder cls, ClassHolderTransformerContext context) {
        String name = cls.getName();
        boolean timer = name.equals("java.util.Timer");
        if (!timer && !name.equals("java.util.TimerTask")) return;
        Set<String> fields = timer ? Set.of("tasks", "cancelled", "threadName", "daemon")
                                  : Set.of("timer", "nativeTimerId");
        require(cls.getParent().equals("java.lang.Object") && cls.getFields().size() == fields.size()
            && cls.getFields().stream().allMatch(field -> fields.contains(field.getName()))
            && cls.getMethods().size() == (timer ? 14 : 3));
        if (timer) {
            require(cls.getField("tasks").getType().equals(ValueType.object("java.util.Set"))
                && cls.getField("cancelled").getType().equals(ValueType.BOOLEAN)
                && cls.getField("daemon").getType().equals(ValueType.BOOLEAN)
                && cls.getField("threadName").getType().equals(ValueType.object("java.lang.String")));
        } else {
            require(cls.getField("timer").getType().equals(ValueType.object("java.util.Timer"))
                && cls.getField("nativeTimerId").getType().equals(ValueType.INTEGER));
        }
        String sdk = "dev.latent.guest.runtime.util." + (timer ? "Timer" : "TimerTask");
        var source = context.getHierarchy().getClassSource().get(sdk);
        require(source != null && source.getField(timer ? "pendingWork" : "lastScheduled") != null);
        var template = new ClassRefsRenamer(new ReferenceCache(), identity -> {
            if (identity.equals("dev.latent.guest.runtime.util.Timer")) return "java.util.Timer";
            if (identity.equals("dev.latent.guest.runtime.util.TimerTask")) return "java.util.TimerTask";
            return identity;
        }).rename(ModelUtils.copyClass(source));
        require(template.getName().equals(name) && template.getParent().equals("java.lang.Object")
            && template.getField(timer ? "pendingWork" : "lastScheduled") != null);
        // Validate and copy the complete source before mutating the maintained
        // model. The SDK class source and its program owners remain unchanged.
        for (var field : new ArrayList<>(cls.getFields())) cls.removeField(field);
        for (var method : new ArrayList<>(cls.getMethods())) cls.removeMethod(method);
        for (var field : new ArrayList<>(template.getFields())) {
            template.removeField(field); cls.addField(field);
        }
        for (var method : new ArrayList<>(template.getMethods())) {
            template.removeMethod(method); cls.addMethod(method);
        }
        cls.getInterfaces().clear(); cls.getInterfaces().addAll(template.getInterfaces());
        cls.getModifiers().clear(); cls.getModifiers().addAll(template.getModifiers());
    }
}

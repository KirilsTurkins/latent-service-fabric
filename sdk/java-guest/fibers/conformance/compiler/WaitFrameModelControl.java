package dev.latent.guest.runtime.compiler;

import java.util.List;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Actual locked classlib IR; developer classes are never initialized. */
public final class WaitFrameModelControl {
    private static final String ASYNC = "org.teavm.interop.Async";
    private static final ValueType CALLBACK = ValueType.object("org.teavm.interop.AsyncCallback");
    private static final String SUPPORT = "dev.latent.guest.runtime.Monitors";

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static void call(MethodHolder method, MethodReference expected) {
        require(method.getProgram() != null, "real-owned-frame-wrapper");
        int count = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction invoke) {
                require(invoke.getMethod().equals(expected), "exact-owned-frame-target");
                count++;
            }
        }
        require(count == 1, "one-owned-frame-target");
    }

    private static void pair(ClassHolder cls, MethodDescriptor original, String rawName, String hook,
                             ValueType... wrapperArguments) {
        var standard = cls.getMethod(original);
        require(standard != null && !standard.getModifiers().contains(ElementModifier.NATIVE)
                && standard.getAnnotations().get(ASYNC) == null, "standard-api-resumable-java-frame");
        var nativeDescriptor = new MethodDescriptor(rawName, original.getSignature());
        var nativeEntry = cls.getMethod(nativeDescriptor);
        require(nativeEntry != null && nativeEntry.getProgram() == null
                && nativeEntry.getModifiers().contains(ElementModifier.NATIVE)
                && nativeEntry.getAnnotations().get(ASYNC) != null, "maintained-native-async-entry");
        var callbackSignature = new ValueType[original.parameterCount() + 2];
        System.arraycopy(original.getParameterTypes(), 0, callbackSignature, 0, original.parameterCount());
        callbackSignature[original.parameterCount()] = CALLBACK;
        callbackSignature[original.parameterCount() + 1] = ValueType.VOID;
        var callback = cls.getMethod(new MethodDescriptor(rawName, callbackSignature));
        require(callback != null && callback.getProgram() != null, "maintained-callback-pair");
        require(cls.getMethod(new MethodDescriptor(original.getName(), callbackSignature)) == null,
                "no-unowned-callback-entry");
        call(standard, new MethodReference(SUPPORT, hook, wrapperArguments));
    }

    public static void main(String[] arguments) {
        var loader = WaitFrameModelControl.class.getClassLoader();
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(loader), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        var sleep = new MethodDescriptor("sleep", ValueType.LONG, ValueType.VOID);
        var wait = new MethodDescriptor("waitImpl", ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
        var originalThread = source.get("java.lang.Thread");
        var originalObject = source.get("java.lang.Object");
        require(originalThread.getMethod(sleep).getModifiers().contains(ElementModifier.NATIVE)
                && originalObject.getMethod(wait).getModifiers().contains(ElementModifier.NATIVE),
                "actual-original-native-frame-negative");
        var thread = ModelUtils.copyClass(originalThread);
        var object = ModelUtils.copyClass(originalObject);
        var sleeping = thread.getMethod(sleep);
        var waiting = object.getMethod(wait);
        var sleepThrows = List.copyOf(sleeping.getThrownTypes());
        var waitThrows = List.copyOf(waiting.getThrownTypes());
        SleepContinuations.transform(thread);
        WaitContinuations.transform(object);
        pair(thread, sleep, "lsfOwnedSleep", "ownedSleep", ValueType.LONG, ValueType.VOID);
        pair(object, wait, "lsfOwnedWait", "ownedWait", ValueType.object("java.lang.Object"),
             ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
        require(thread.getMethod(sleep) == sleeping && object.getMethod(wait) == waiting,
                "standard-method-owners-preserved");
        require(thread.getMethod(new MethodDescriptor("lsfOwnedSleep", sleep.getSignature())).getThrownTypes()
                .equals(sleepThrows), "sleep-throws-preserved");
        require(object.getMethod(new MethodDescriptor("lsfOwnedWait", wait.getSignature())).getThrownTypes()
                .equals(waitThrows), "wait-throws-preserved");
        var wrongThread = ModelUtils.copyClass(originalThread);
        wrongThread.getMethod(sleep).getAnnotations().remove(ASYNC);
        try { SleepContinuations.transform(wrongThread); throw new AssertionError("unknown-async-shape-accepted"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unreviewed-maintained-sleep-handler"), "closed-native-shape");
        }
        try { WaitContinuations.transform(object); throw new AssertionError("repeated-port-accepted"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unreviewed-maintained-monitor-handler"), "closed-repeated-shape");
        }
        var unrelated = new ClassHolder("outside.application.Thread");
        SleepContinuations.transform(unrelated);
        WaitContinuations.transform(unrelated);
        require(unrelated.getMethods().isEmpty(), "application-identity-preserved");
        System.out.println("WAIT_FRAME_MODEL_CONTROL PASS original-native-negative;real-native-callback-pairs;"
            + "resumed-java-frame-owners;throws-and-standard-owners;shape-and-repeat-negatives;application-identity");
    }
}

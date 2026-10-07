package dev.latent.guest.runtime.compiler;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.teavm.backend.lowlevel.transform.CoroutineTransformation;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.ClassReaderSource;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.MonitorEnterInstruction;
import org.teavm.model.instructions.MonitorExitInstruction;
import org.teavm.model.instructions.SwitchInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;
import org.teavm.platform.plugin.AsyncMethodProcessor;
import org.teavm.vm.WaitFramePluginOrder;

/** Actual locked classlib IR; developer classes are never initialized. */
public final class WaitFrameModelControl {
    private static final String ASYNC = "org.teavm.interop.Async";
    private static final ValueType CALLBACK = ValueType.object("org.teavm.interop.AsyncCallback");
    private static final String SUPPORT = "dev.latent.guest.runtime.Monitors";
    private static final MethodReference SUSPEND = new MethodReference("org.teavm.runtime.Fiber", "suspend",
        ValueType.object("org.teavm.runtime.Fiber$AsyncCall"), ValueType.object("java.lang.Object"));

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

    private static List<ClassHolder> lowerAsync(ClassHolder cls) {
        var generated = new ArrayList<ClassHolder>();
        var context = (ClassHolderTransformerContext) Proxy.newProxyInstance(
            WaitFrameModelControl.class.getClassLoader(), new Class<?>[] { ClassHolderTransformerContext.class },
            (proxy, method, arguments) -> {
                require(method.getName().equals("submit"), "exact-async-processor-context-operation");
                generated.add((ClassHolder) arguments[0]);
                return null;
            });
        new AsyncMethodProcessor(true).transformClass(cls, context);
        return generated;
    }

    private static void loweredPair(ClassReaderSource source, ClassHolder cls, MethodDescriptor original,
                                    String rawName, String hook,
                                    ValueType... wrapperArguments) {
        var nativeEntry = cls.getMethod(new MethodDescriptor(rawName, original.getSignature()));
        var generated = lowerAsync(cls);
        require(nativeEntry.getProgram() != null && !nativeEntry.hasModifier(ElementModifier.NATIVE),
                "actual-low-level-fiber-entry");
        int suspensions = 0;
        for (var block : nativeEntry.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof InvokeInstruction invoke
                    && invoke.getMethod().equals(new MethodReference("org.teavm.runtime.Fiber", "suspend",
                        ValueType.object("org.teavm.runtime.Fiber$AsyncCall"), ValueType.object("java.lang.Object"))))
                suspensions++;
        }
        require(suspensions == 1, "one-maintained-fiber-suspension");
        var callbackSignature = new ValueType[original.parameterCount() + 2];
        System.arraycopy(original.getParameterTypes(), 0, callbackSignature, 0, original.parameterCount());
        callbackSignature[original.parameterCount()] = CALLBACK;
        callbackSignature[original.parameterCount() + 1] = ValueType.VOID;
        var expected = new MethodReference(cls.getName(), rawName, callbackSignature);
        int callbacks = 0;
        for (var generatedClass : generated) {
            var run = generatedClass.getMethod(new MethodDescriptor("run", CALLBACK, ValueType.VOID));
            for (var block : run.getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof InvokeInstruction invoke && invoke.getMethod().equals(expected)) callbacks++;
            }
        }
        require(callbacks == 1, "actual-generated-owned-callback-target");
        call(cls.getMethod(original), new MethodReference(SUPPORT, hook, wrapperArguments));
        coroutine(source, nativeEntry, SUSPEND, false);
    }

    private static Program withoutEntry(Program program) {
        var original = ProgramUtils.copy(program);
        var entry = original.basicBlockAt(0);
        var body = original.basicBlockAt(1);
        require(entry.instructionCount() == 1 && entry.getFirstInstruction() instanceof JumpInstruction jump
                && jump.getTarget() == body, "empty-coroutine-entry");
        entry.removeAllInstructions();
        entry.addAll(ProgramUtils.copyInstructions(body.getFirstInstruction(), body.getLastInstruction(), original));
        original.deleteBasicBlock(1);
        original.pack();
        return original;
    }

    private static Program coroutine(ClassReaderSource source, MethodHolder method, MethodReference target,
                                     boolean originalNegative) {
        var program = method.getProgram();
        require(program != null && program.basicBlockCount() >= 2, "resumable-body-beyond-entry");
        var entry = program.basicBlockAt(0);
        require(entry.instructionCount() == 1 && entry.getFirstInstruction() instanceof JumpInstruction jump
                && jump.getTarget() == program.basicBlockAt(1), "maintained-coroutine-entry-convention");
        var targets = target == null ? Set.<MethodReference>of() : Set.of(target);
        if (originalNegative) {
            var original = withoutEntry(program);
            try {
                new CoroutineTransformation(source, targets, true).apply(original, method.getReference());
                throw new AssertionError("original-first-block-suspension-accepted");
            } catch (ArrayIndexOutOfBoundsException expected) {
                require(expected.getStackTrace()[0].getClassName().equals("org.teavm.model.util.LivenessAnalyzer"),
                        "exact-original-coroutine-liveness-failure");
            }
        }
        var lowered = ProgramUtils.copy(program);
        new CoroutineTransformation(source, targets, true).apply(lowered, method.getReference());
        require(lowered.basicBlockCount() > program.basicBlockCount(), "actual-coroutine-split");
        int resumptions = 0;
        int calls = 0;
        for (var block : lowered.getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof SwitchInstruction states) resumptions += states.getEntries().size();
            if (instruction instanceof InvokeInstruction invoke && invoke.getMethod().equals(target)) calls++;
        }
        require(resumptions == 1 && (target == null || calls == 1), "one-original-resumable-operation");
        return lowered;
    }

    private static void continuationWrappers(ClassReaderSource source, ClassHolder thread, ClassHolder object) {
        var hooks = new ClassHolder(SUPPORT);
        var rawSleep = new MethodHolder("rawSleep", ValueType.LONG, ValueType.VOID);
        var rawWait = new MethodHolder("rawWait", ValueType.object("java.lang.Object"),
            ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
        rawSleep.getModifiers().add(ElementModifier.STATIC);
        rawWait.getModifiers().add(ElementModifier.STATIC);
        hooks.addMethod(rawSleep);
        hooks.addMethod(rawWait);
        SleepContinuations.transform(hooks);
        WaitContinuations.transform(hooks);
        var join = thread.getMethod(new MethodDescriptor("join", ValueType.LONG, ValueType.INTEGER, ValueType.VOID));
        require(join != null && join.getProgram() != null, "actual-standard-join-method");
        RuntimePlugin.threadMethod(join, join.getProgram());
        var methods = List.of(thread.getMethod(new MethodDescriptor("sleep", ValueType.LONG, ValueType.VOID)),
            thread.getMethod(new MethodDescriptor("sleep", ValueType.LONG, ValueType.INTEGER, ValueType.VOID)),
            object.getMethod(new MethodDescriptor("waitImpl", ValueType.LONG, ValueType.INTEGER, ValueType.VOID)),
            rawSleep, rawWait, join);
        for (var method : methods) {
            require(method.getProgram().basicBlockCount() == 2, "two-block-owned-wrapper");
            MethodReference target = null;
            for (var instruction : method.getProgram().basicBlockAt(1)) {
                if (instruction instanceof InvokeInstruction invoke) {
                    require(target == null, "one-wrapper-operation");
                    target = invoke.getMethod();
                }
            }
            require(target != null, "resumable-wrapper-operation-retained");
            coroutine(source, method, target, true);
        }
    }

    private static void synchronizedContinuations(ClassReaderSource source) {
        for (boolean isStatic : List.of(false, true)) {
            var cls = new ClassHolder("outside.application.MonitorEntry");
            var method = new MethodHolder("run", ValueType.VOID);
            cls.addMethod(method);
            method.getModifiers().add(ElementModifier.SYNCHRONIZED);
            if (isStatic) method.getModifiers().add(ElementModifier.STATIC);
            var program = new Program();
            program.createVariable();
            program.createBasicBlock().add(new ExitInstruction());
            method.setProgram(program);
            SynchronizedMethods.lower(cls.getName(), method);
            require(method.getProgram().basicBlockCount() == 4, "monitor-acquisition-outside-protected-body");
            var lowered = coroutine(source, method, null, true);
            int acquisitions = 0;
            int releases = 0;
            for (var block : lowered.getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof MonitorEnterInstruction) acquisitions++;
                if (instruction instanceof MonitorExitInstruction) releases++;
            }
            require(acquisitions == 1 && releases == 2, "original-normal-and-exception-monitor-release");
        }
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
        require(WaitFramePluginOrder.ordered().equals(List.of("dev.latent.guest.runtime.compiler.RuntimePlugin",
            "org.teavm.platform.plugin.PlatformPlugin")), "actual-maintained-plugin-order");
        var platformFirst = ModelUtils.copyClass(originalObject);
        lowerAsync(platformFirst);
        require(platformFirst.getMethod(wait).getProgram() != null
                && !platformFirst.getMethod(wait).hasModifier(ElementModifier.NATIVE), "actual-platform-first-negative");
        try { WaitContinuations.transform(platformFirst); throw new AssertionError("platform-first-port-accepted"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("unreviewed-maintained-monitor-handler"), "closed-platform-first-shape");
        }
        var thread = ModelUtils.copyClass(originalThread);
        var object = ModelUtils.copyClass(originalObject);
        var sleeping = thread.getMethod(sleep);
        var waiting = object.getMethod(wait);
        var sleepThrows = List.copyOf(sleeping.getThrownTypes());
        var waitThrows = List.copyOf(waiting.getThrownTypes());
        MonitorContinuations.transform(object);
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
        continuationWrappers(source, thread, object);
        synchronizedContinuations(source);
        loweredPair(source, thread, sleep, "lsfOwnedSleep", "ownedSleep", ValueType.LONG, ValueType.VOID);
        loweredPair(source, object, wait, "lsfOwnedWait", "ownedWait", ValueType.object("java.lang.Object"),
                    ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
        var unrelated = new ClassHolder("outside.application.Thread");
        SleepContinuations.transform(unrelated);
        WaitContinuations.transform(unrelated);
        require(unrelated.getMethods().isEmpty(), "application-identity-preserved");
        System.out.println("WAIT_FRAME_MODEL_CONTROL PASS original-native-negative;real-native-callback-pairs;"
            + "resumed-java-frame-owners;throws-and-standard-owners;actual-platform-order;"
            + "async-lowered-owned-pairs;platform-first-negative;shape-and-repeat-negatives;application-identity;"
            + "coroutine-wrappers=6;coroutine-monitors=2;coroutine-native-pairs=2;entry-layout-negative");
    }
}

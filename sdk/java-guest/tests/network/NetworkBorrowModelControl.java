package dev.latent.guest.runtime.compiler;

import java.util.List;
import java.util.Set;
import org.teavm.classlib.impl.ClasslibSubstitutionPolicy;
import org.teavm.model.*;
import org.teavm.model.instructions.*;
import org.teavm.model.util.ModelUtils;
import org.teavm.parsing.ClasspathClassHolderSource;
import org.teavm.parsing.ClasspathResourceProvider;
import org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping;

/** Pinned TeaVM model and actual RuntimePlugin; no component or host execution. */
public final class NetworkBorrowModelControl {
    private static final String RESOURCE = "dev.latent.guest.Resource";
    private static final String WRITER = "dev.latent.guest.Wire$Writer";
    private static final String HOST_CALLS = "dev.latent.guest.runtime.HostCalls";
    private static final MethodReference CHECKPOINT = new MethodReference(
        "dev.latent.guest.runtime.Activation", "checkpoint", ValueType.VOID);

    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static int count(MethodHolder method, Class<?> instructionType) {
        int result = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block)
            if (instructionType.isInstance(instruction)) result++;
        return result;
    }

    private static int checkpoints(MethodHolder method) {
        int result = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block)
            if (instruction instanceof InvokeInstruction call && call.getMethod().equals(CHECKPOINT)) result++;
        return result;
    }

    private static void transform(ClassHolder cls) throws Exception {
        var plugin = new RuntimePlugin();
        var classesField = RuntimePlugin.class.getDeclaredField("applicationClasses");
        classesField.setAccessible(true);
        @SuppressWarnings("unchecked") var classes = (Set<String>)classesField.get(plugin);
        require(classes.add(cls.getName()), "selected-class");
        var transform = RuntimePlugin.class.getDeclaredMethod("transform", ClassHolder.class,
            ClassHolderTransformerContext.class);
        transform.setAccessible(true);
        transform.invoke(plugin, cls, null);
    }

    private static void actual(ClasspathClassHolderSource source, String owner, MethodDescriptor... descriptors)
            throws Exception {
        var original = source.get(owner);
        require(original != null, "actual-source-class");
        var selected = ModelUtils.copyClass(original);
        for (var descriptor : descriptors) {
            var method = selected.getMethod(descriptor);
            require(method != null && method.getProgram() != null, "actual-source-method");
            require(count(method, MonitorEnterInstruction.class) > 0
                && count(method, MonitorExitInstruction.class) > 0, "actual-monitor-instructions");
            require(checkpoints(method) == 0, "original-has-no-checkpoint");
        }
        transform(selected);
        for (var descriptor : descriptors) {
            var method = selected.getMethod(descriptor);
            require(count(method, MonitorEnterInstruction.class) > 0
                && count(method, MonitorExitInstruction.class) > 0, "transformed-monitor-instructions");
            // Stronger than checking just the locked region: no compiler-inserted
            // checkpoint anywhere in these finite, monitor-bearing methods.
            require(checkpoints(method) == 0, "checkpoint-in-ownership-method");
        }
    }

    private static void loopControl() throws Exception {
        var cls = new ClassHolder("qualification.NetworkBorrowSelectedLoop");
        var method = new MethodHolder("run", ValueType.VOID);
        method.getModifiers().add(ElementModifier.STATIC);
        var program = new Program();
        program.createVariable();
        var block = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(block);
        block.add(jump);
        method.setProgram(program);
        cls.addMethod(method);
        transform(cls);
        require(checkpoints(method) == 1, "selected-loop-control-must-instrument");
    }

    private static void ownedCallback(ClasspathClassHolderSource source) throws Exception {
        var original = source.get(HOST_CALLS);
        require(original != null, "actual-owned-callback-class");
        var selected = ModelUtils.copyClass(original);
        var descriptor = new MethodDescriptor("suspendOwned", ValueType.INTEGER, ValueType.object("org.teavm.interop.Address"),
            ValueType.INTEGER, ValueType.object(HOST_CALLS + "$Call"),
            ValueType.object("org.teavm.interop.AsyncCallback"), ValueType.VOID);
        var method = selected.getMethod(descriptor);
        require(method != null && method.getProgram() != null, "actual-owned-callback-method");
        transform(selected);
        require(checkpoints(method) == 0, "owned-callback-checkpoint");
        int beginnings = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (!(instruction instanceof InvokeInstruction call)) continue;
            require(!(call.getMethod().getClassName().equals("org.teavm.interop.Address")
                && call.getMethod().getName().equals("ofData")), "owned-callback-no-java-raw-pointer");
            if (call.getMethod().getClassName().equals(HOST_CALLS)
                    && call.getMethod().getName().equals("begin")) {
                require(call.getArguments().size() == 3, "owned-callback-native-entry-shape");
                beginnings++;
            }
        }
        require(beginnings == 1, "single-owned-native-entry");
    }

    private static void ownedCopy(ClasspathClassHolderSource source) throws Exception {
        var original = source.get(HOST_CALLS + "$Call");
        require(original != null, "actual-owned-copy-class");
        var selected = ModelUtils.copyClass(original);
        var descriptor = new MethodDescriptor("callOwned", ValueType.INTEGER, ValueType.arrayOf(ValueType.BYTE),
            ValueType.INTEGER, ValueType.object("org.teavm.interop.Address"));
        var method = selected.getMethod(descriptor);
        require(method != null && method.getProgram() != null, "actual-owned-copy-method");
        transform(selected);
        int reads = 0, writes = 0, allocations = 0, submissions = 0;
        for (var block : method.getProgram().getBasicBlocks()) for (var instruction : block) {
            if (instruction instanceof GetElementInstruction) reads++;
            if (!(instruction instanceof InvokeInstruction call)) continue;
            var target = call.getMethod();
            require(!(target.getClassName().equals("org.teavm.interop.Address")
                && target.getName().equals("ofData")), "owned-copy-no-java-raw-pointer");
            if (target.getClassName().equals("org.teavm.interop.Address")
                    && target.getName().equals("putByte")) writes++;
            if (target.getClassName().equals(HOST_CALLS) && target.getName().equals("allocateScratch")) allocations++;
            if (target.getClassName().equals(HOST_CALLS) && target.getName().equals("suspendOwned")) submissions++;
        }
        require(reads >= 1 && writes == 1 && allocations == 1 && submissions == 1,
                "owned-copy-managed-array-to-native-frame");
    }

    public static void main(String[] args) throws Exception {
        var source = new ClasspathClassHolderSource(new ClasspathResourceProvider(
            NetworkBorrowModelControl.class.getClassLoader()), new ReferenceCache(),
            DefaultSubstituteClassNameMapping.createWithPolicies(List.of(new ClasslibSubstitutionPolicy())));
        actual(source, RESOURCE,
            new MethodDescriptor("borrow", ValueType.INTEGER, ValueType.INTEGER),
            new MethodDescriptor("releaseBorrow", ValueType.INTEGER, ValueType.VOID),
            new MethodDescriptor("consume", ValueType.INTEGER),
            new MethodDescriptor("close", ValueType.VOID));
        actual(source, WRITER,
            new MethodDescriptor("rootInput", ValueType.VOID),
            new MethodDescriptor("unrootInput", ValueType.VOID));
        ownedCallback(source);
        ownedCopy(source);
        loopControl();
        System.out.println("NETWORK_BORROW_MODEL PASS actual-resource-and-writer;monitors;no-checkpoints;owned-native-copy-entry;selected-loop-positive;COMPONENT_QUALIFICATION=pending");
    }
}

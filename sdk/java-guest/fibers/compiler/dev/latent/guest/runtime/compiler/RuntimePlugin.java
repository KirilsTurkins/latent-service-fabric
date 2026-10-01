package dev.latent.guest.runtime.compiler;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import org.teavm.common.LoopGraph;
import org.teavm.model.ClassHolder;
import org.teavm.model.ClassHolderTransformerContext;
import org.teavm.model.Instruction;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.vm.spi.TeaVMHost;
import org.teavm.vm.spi.TeaVMPlugin;

/** SDK-owned compiler extension. The closure index is emitted from actual class
 * files, not a package allowlist or an application-executed compiler plugin. */
public final class RuntimePlugin implements TeaVMPlugin {
    private static final String RUNTIME = "dev.latent.guest.runtime.Activation";
    private final Set<String> applicationClasses = new HashSet<>();

    @Override public void install(TeaVMHost host) {
        try (var input = getClass().getClassLoader().getResourceAsStream("META-INF/latent/runtime-checkpoints.classes")) {
            if (input == null) throw new IllegalStateException("missing-owned-runtime-checkpoint-index");
            try (var reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!applicationClasses.add(line)) throw new IllegalStateException("duplicate-runtime-checkpoint-class");
                }
            }
        } catch (java.io.IOException error) { throw new IllegalStateException(error); }
        host.add(this::transform);
    }

    private static InvokeInstruction call(String name, ValueType... signature) {
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL);
        call.setMethod(new MethodReference(RUNTIME, name, signature));
        return call;
    }

    private void transform(ClassHolder cls, ClassHolderTransformerContext context) {
        normalizeOwnedConcurrentReferences(cls);
        TimeUnitMethods.transform(cls, context);
        MonitorContinuations.transform(cls);
        SleepContinuations.transform(cls);
        WaitContinuations.transform(cls);
        boolean thread = cls.getName().equals("java.lang.Thread");
        boolean monotonic = thread || cls.getName().equals("java.lang.Object")
            || cls.getName().equals("org.teavm.runtime.EventQueue");
        for (var method : cls.getMethods()) {
            var program = method.getProgram();
            if (program == null || program.basicBlockCount() == 0) continue;
            SynchronizedMethods.lower(cls.getName(), method);
            if (thread) threadMethod(method, program);
            if (monotonic) {
                for (var block : program.getBasicBlocks()) for (Instruction instruction : block) {
                    if (instruction instanceof InvokeInstruction invoke
                            && invoke.getMethod().getClassName().equals("java.lang.System")
                            && invoke.getMethod().getName().equals("currentTimeMillis")) {
                        invoke.setMethod(new MethodReference(RUNTIME, "monotonicMillis", ValueType.LONG));
                    }
                }
            }
            if (!applicationClasses.contains(cls.getName()) || method.getName().equals("<clinit>")
                    || method.getAnnotations().get("org.teavm.interop.Unmanaged") != null) continue;
            var loops = new LoopGraph(ProgramUtils.buildControlFlowGraph(program));
            var headers = new HashSet<Integer>();
            for (int index = 0; index < loops.size(); index++) {
                var loop = loops.loopAt(index);
                if (loop != null) headers.add(loop.getHead());
            }
            for (int index : headers) {
                var first = program.basicBlockAt(index).getFirstInstruction();
                if (first != null) first.insertPrevious(call("checkpoint", ValueType.VOID));
            }
        }
    }

    private static boolean privateConcurrentHelper(String suffix) {
        return suffix.equals("ManagedExecutor") || suffix.startsWith("ManagedExecutor$")
            || suffix.startsWith("AbstractExecutorService$") || suffix.startsWith("Executors$")
            || suffix.startsWith("TimeUnit$");
    }

    private static String concurrentReference(String name) {
        String standard = RuntimeSubstitution.STANDARD;
        String sdk = RuntimeSubstitution.SDK;
        if (name.startsWith(standard)) {
            String suffix = name.substring(standard.length());
            if (privateConcurrentHelper(suffix)) return sdk + suffix;
        } else if (name.startsWith(sdk)) {
            String suffix = name.substring(sdk.length());
            if (RuntimeSubstitution.API.contains(suffix)) return standard + suffix;
        }
        return name;
    }

    private static void normalizeOwnedConcurrentReferences(ClassHolder cls) {
        String name = cls.getName();
        boolean api = name.startsWith(RuntimeSubstitution.STANDARD)
            && RuntimeSubstitution.API.contains(name.substring(RuntimeSubstitution.STANDARD.length()));
        boolean helper = name.startsWith(RuntimeSubstitution.SDK)
            && privateConcurrentHelper(name.substring(RuntimeSubstitution.SDK.length()));
        if (!api && !helper) return;
        // Package substitution can give the same SDK type two class identities.
        // Normalize only trusted API bodies and their private implementation;
        // captured application/library bytecode retains its standard symbols.
        ClassHolder normalized = new ClassRefsRenamer(new ReferenceCache(), RuntimePlugin::concurrentReference).rename(cls);
        if (normalized != cls) throw new IllegalStateException("unexpected-owned-runtime-class-alias");
    }

    private static void threadMethod(MethodHolder method, Program program) {
        if (method.getName().equals("start") && method.parameterCount() == 0) {
            var admission = call("starting", ValueType.object("java.lang.Thread"), ValueType.VOID);
            admission.setArguments(program.variableAt(0));
            program.basicBlockAt(0).getFirstInstruction().insertPrevious(admission);
        } else if (method.getName().equals("runThread") && method.parameterCount() == 0) {
            for (var block : program.getBasicBlocks()) for (Instruction instruction : block) {
                if (instruction instanceof ExitInstruction) {
                    var completion = call("finished", ValueType.object("java.lang.Thread"), ValueType.VOID);
                    completion.setArguments(program.variableAt(0));
                    instruction.insertPrevious(completion);
                }
            }
        } else if (method.getDescriptor().equals(new MethodDescriptor("isAlive", ValueType.BOOLEAN))) {
            var replacement = new Program();
            var self = replacement.createVariable();
            var result = replacement.createVariable();
            var block = replacement.createBasicBlock();
            var alive = call("alive", ValueType.object("java.lang.Thread"), ValueType.BOOLEAN);
            alive.setArguments(self);
            alive.setReceiver(result);
            block.add(alive);
            var exit = new ExitInstruction();
            exit.setValueToReturn(result);
            block.add(exit);
            method.setProgram(replacement);
        } else if (method.getDescriptor().equals(new MethodDescriptor("join", ValueType.LONG, ValueType.INTEGER, ValueType.VOID))) {
            var replacement = new Program();
            var self = replacement.createVariable();
            var millis = replacement.createVariable();
            var nanos = replacement.createVariable();
            var block = replacement.createBasicBlock();
            var join = call("join", ValueType.object("java.lang.Thread"), ValueType.LONG, ValueType.INTEGER, ValueType.VOID);
            join.setArguments(self, millis, nanos);
            block.add(join);
            block.add(new ExitInstruction());
            method.setProgram(replacement);
        }
    }
}

package dev.latent.guest.runtime.compiler;

import java.io.OutputStream;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import org.teavm.cache.ClassIO;
import org.teavm.cache.InMemorySymbolTable;
import org.teavm.cache.ProgramIO;
import org.teavm.model.ClassHolder;
import org.teavm.model.ElementModifier;
import org.teavm.model.MethodDescriptor;
import org.teavm.model.MethodReference;
import org.teavm.model.PreOptimizingClassHolderSource;
import org.teavm.model.ProgramReader;
import org.teavm.model.ReferenceCache;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.util.ModelUtils;
import org.teavm.model.util.ProgramUtils;
import org.teavm.parsing.ClassRefsRenamer;
import org.teavm.parsing.Parser;

/** Keep the pinned small power tables out of the generic recursive multiplier.
 * The ordinary application multiply implementation is not changed or exempted
 * from checkpoint analysis. The replacement's complete closure is still proved.
 */
final class BoundedMathInitialization {
    private static final String NAME = "java.math.Multiplication";
    private static final String DONOR = "org.teavm.classlib.java.math.TMultiplication";
    private static final String INTEGER_DONOR = "org.teavm.classlib.java.math.TBigInteger";
    private static final ValueType INTEGER = ValueType.object("java.math.BigInteger");
    private static final MethodDescriptor INITIALIZER = new MethodDescriptor("<clinit>", ValueType.VOID);
    private static final MethodReference MULTIPLY = new MethodReference("java.math.BigInteger", "multiply",
            INTEGER, INTEGER);
    private static final MethodReference ITERATIVE = new MethodReference(NAME, "multiplyPAP",
            INTEGER, INTEGER, INTEGER);

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("unexpected-maintained-math-initialization");
    }

    private static boolean bounded(ProgramReader program) {
        if (program == null || program.basicBlockCount() > 256 || program.variableCount() > 4096) return false;
        long work = 0;
        for (var block : program.getBasicBlocks()) {
            work += block.instructionCount() + block.readTryCatchBlocks().size();
            for (var phi : block.readPhis()) work += 1 + phi.readIncomings().size();
            if (work > 16384) return false;
        }
        return true;
    }

    private static boolean sameBody(ProgramReader left, ProgramReader right) throws Exception {
        if (!bounded(left) || !bounded(right)) return false;
        var io = new ProgramIO(new ReferenceCache(), new InMemorySymbolTable(),
                new InMemorySymbolTable(), new InMemorySymbolTable());
        var first = MessageDigest.getInstance("SHA-256");
        var second = MessageDigest.getInstance("SHA-256");
        try (var a = new DigestOutputStream(OutputStream.nullOutputStream(), first);
             var b = new DigestOutputStream(OutputStream.nullOutputStream(), second)) {
            io.write(ProgramUtils.copy(left), a);
            io.write(ProgramUtils.copy(right), b);
        }
        return MessageDigest.isEqual(first.digest(), second.digest());
    }

    private static boolean sameDeclaration(ClassHolder expected, ClassHolder actual) throws Exception {
        var a = ModelUtils.copyClass(expected);
        var b = ModelUtils.copyClass(actual);
        // Only the initializer and its direct replacement are transformed.
        // Do not certify unrelated bodies merely from their declaring class.
        for (var method : a.getMethods()) method.setProgram(null);
        for (var method : b.getMethods()) method.setProgram(null);
        var io = new ClassIO(new ReferenceCache(), new InMemorySymbolTable(),
                new InMemorySymbolTable(), new InMemorySymbolTable());
        var first = MessageDigest.getInstance("SHA-256");
        var second = MessageDigest.getInstance("SHA-256");
        try (var outA = new DigestOutputStream(OutputStream.nullOutputStream(), first);
             var outB = new DigestOutputStream(OutputStream.nullOutputStream(), second)) {
            io.writeClass(outA, a);
            io.writeClass(outB, b);
        }
        return MessageDigest.isEqual(first.digest(), second.digest());
    }

    static void transform(ClassHolder cls) {
        if (!cls.getName().equals(NAME)) return;
        try {
            var loader = BoundedMathInitialization.class.getClassLoader();
            byte[] bytes;
            try (var input = loader.getResourceAsStream(DONOR.replace('.', '/') + ".class")) {
                require(input != null);
                bytes = input.readNBytes(32769);
                require(bytes.length <= 32768 && MessageDigest.isEqual(
                        MessageDigest.getInstance("SHA-256").digest(bytes),
                        HexFormat.of().parseHex("4503818e36f8595cae20b26f94b7e955e8bb26e9966e4003732b1ab8e7868067")));
            }
            // Parse the same authenticated bytes, not a second resource read.
            var node = new org.teavm.asm.tree.ClassNode();
            new org.teavm.asm.ClassReader(bytes).accept(node, 0);
            var parsed = new Parser(new ReferenceCache()).parseClass(node);
            var source = new PreOptimizingClassHolderSource(name -> name.equals(DONOR) ? parsed : null);
            var expected = source.get(DONOR);
            require(expected != null && cls.getMethods().size() <= 64 && cls.getFields().size() <= 16);
            // The JCL substitution changes these two identities in this class's
            // declarations and initializer. Other body references are not used
            // as a certificate by this transformation.
            expected = new ClassRefsRenamer(new ReferenceCache(), name ->
                    name.equals(DONOR) ? NAME : name.equals(INTEGER_DONOR) ? "java.math.BigInteger" : name)
                    .rename(expected);
            var original = expected.getMethod(INITIALIZER);
            var actual = cls.getMethod(INITIALIZER);
            var replacement = cls.getMethod(ITERATIVE.getDescriptor());
            var originalReplacement = expected.getMethod(ITERATIVE.getDescriptor());
            require(original != null && actual != null && replacement != null && originalReplacement != null
                    && actual.hasModifier(ElementModifier.STATIC)
                    && replacement.hasModifier(ElementModifier.STATIC)
                    && sameDeclaration(expected, cls)
                    && sameBody(original.getProgram(), actual.getProgram())
                    && sameBody(originalReplacement.getProgram(), replacement.getProgram()));
            // Validate every selected site before modifying any. The exact
            // preimage creates 32 positive powers; only indices 19..31 call
            // multiply, with a factor of five or ten. The shorter operand has
            // one word (< the pinned Karatsuba threshold of 63), so the old
            // implementation already selects multiplyPAP for these values.
            var calls = new ArrayList<InvokeInstruction>();
            for (var block : actual.getProgram().getBasicBlocks()) for (var instruction : block) {
                if (instruction instanceof InvokeInstruction invoke && invoke.getMethod().equals(MULTIPLY)) {
                    require(invoke.getType() == InvocationType.VIRTUAL && invoke.getInstance() != null
                            && invoke.getArguments().size() == 1 && invoke.getReceiver() != null);
                    calls.add(invoke);
                }
            }
            require(calls.size() == 2);
            for (var invoke : calls) {
                var left = invoke.getInstance();
                var right = invoke.getArguments().get(0);
                invoke.setType(InvocationType.SPECIAL);
                invoke.setInstance(null);
                invoke.setMethod(ITERATIVE);
                invoke.setArguments(left, right);
            }
        } catch (Exception failure) {
            if (failure instanceof IllegalStateException) throw (IllegalStateException) failure;
            throw new IllegalStateException("unexpected-maintained-math-initialization", failure);
        }
    }

    private BoundedMathInitialization() { }
}

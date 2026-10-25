package org.teavm.backend.lowlevel.transform;

import java.lang.reflect.Field;
import java.util.HashSet;
import java.util.Set;
import org.teavm.common.GraphUtils;
import org.teavm.model.BasicBlock;
import org.teavm.model.Incoming;
import org.teavm.model.Phi;
import org.teavm.model.Program;
import org.teavm.model.TryCatchBlock;
import org.teavm.model.Variable;
import org.teavm.model.MethodReference;
import org.teavm.model.ValueType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.BranchingCondition;
import org.teavm.model.instructions.BranchingInstruction;
import org.teavm.model.instructions.IntegerConstantInstruction;
import org.teavm.model.util.ProgramUtils;
import org.teavm.model.text.ListingBuilder;

/** Real pinned TeaVM IR at its irreducible-loop splitting boundary. */
public final class Check {
    private static void jump(BasicBlock from, BasicBlock to) {
        var jump = new JumpInstruction(); jump.setTarget(to); from.add(jump);
    }

    private static void incoming(Phi phi, BasicBlock from, Variable value) {
        var incoming = new Incoming(); incoming.setSource(from); incoming.setValue(value);
        phi.getIncomings().add(incoming);
    }

    private static void branch(BasicBlock from, Variable value, BasicBlock yes, BasicBlock no) {
        var branch = new BranchingInstruction(BranchingCondition.EQUAL);
        branch.setOperand(value); branch.setConsequent(yes); branch.setAlternative(no); from.add(branch);
    }

    private static Set<Integer> sources(Phi phi) {
        var sources = new HashSet<Integer>();
        for (var incoming : phi.getIncomings()) sources.add(incoming.getSource().getIndex());
        return sources;
    }

    private static void entryLiveness(String mode) {
        var program = new Program();
        var entry = program.createBasicBlock();
        var exit = program.createBasicBlock();
        program.createVariable(); // The method's original implicit receiver slot.
        var value = program.createVariable();
        var constant = new IntegerConstantInstruction();
        constant.setReceiver(value); constant.setConstant(42); entry.add(constant);
        var awaited = new MethodReference("control.Await", "await", ValueType.VOID);
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL); call.setMethod(awaited); entry.add(call);
        jump(entry, exit);
        var result = new ExitInstruction(); result.setValueToReturn(value); exit.add(result);
        var transform = new CoroutineTransformation(name -> null, Set.of(awaited), false);
        try {
            transform.apply(program, new MethodReference("control.Owner", "run", ValueType.INTEGER));
        } catch (ArrayIndexOutOfBoundsException failure) {
            var origin = failure.getStackTrace()[0];
            if (!mode.equals("original")
                    || !origin.getClassName().equals("org.teavm.model.util.LivenessAnalyzer")
                    || !origin.getMethodName().equals("liveOut")) {
                throw failure;
            }
            return;
        }
        if (mode.equals("original")) {
            throw new AssertionError("coroutine-control-original-entry-defect-not-observed");
        }
        int calls = 0, pushes = 0;
        var pushInt = new MethodReference("org.teavm.runtime.Fiber", "push", ValueType.INTEGER, ValueType.VOID);
        for (var block : program.getBasicBlocks()) {
            for (var instruction : block) {
                if (instruction instanceof InvokeInstruction) {
                    var method = ((InvokeInstruction) instruction).getMethod();
                    if (method.equals(awaited)) ++calls;
                    if (method.equals(pushInt)) ++pushes;
                }
            }
        }
        // One state number plus the integer live across the original entry call.
        if (calls != 1 || pushes != 2) {
            throw new AssertionError("coroutine-control-entry-live-value-lost-or-call-replayed");
        }
    }

    private static Program copyCostProgram(boolean heavyFirst) {
        var program = new Program();
        var entry = program.createBasicBlock();
        var first = program.createBasicBlock();
        var second = program.createBasicBlock();
        var handler = program.createBasicBlock();
        var seed = program.createVariable();
        var constant = new IntegerConstantInstruction();
        constant.setReceiver(seed); constant.setConstant(42); entry.add(constant);
        branch(entry, seed, first, second);
        for (int i = 1; i <= 2; ++i) {
            var block = program.basicBlockAt(i);
            var other = program.basicBlockAt(3 - i);
            var marker = new IntegerConstantInstruction();
            marker.setReceiver(program.createVariable()); marker.setConstant(i * 100); block.add(marker);
            jump(block, other);
            boolean heavy = (i == 1) == heavyFirst;
            for (int n = 0; n < (heavy ? 3 : 1); ++n) {
                var phi = new Phi(); phi.setReceiver(program.createVariable());
                incoming(phi, entry, seed); incoming(phi, other, seed); block.getPhis().add(phi);
            }
            for (String type : heavy
                    ? new String[] {"java.lang.IllegalArgumentException", "java.lang.IllegalStateException",
                        "java.lang.Throwable"}
                    : new String[] {"java.lang.Throwable"}) {
                var guard = new TryCatchBlock(); guard.setExceptionType(type); guard.setHandler(handler);
                block.getTryCatchBlocks().add(guard);
            }
        }
        handler.setExceptionVariable(program.createVariable()); handler.add(new ExitInstruction());
        return program;
    }

    private static CoroutineTransformation costTransform(Program program) throws Exception {
        var transform = new CoroutineTransformation(null, Set.of(), true);
        Field field = CoroutineTransformation.class.getDeclaredField("program");
        field.setAccessible(true); field.set(transform, program);
        return transform;
    }

    private static void normalizeCost(CoroutineTransformation transform) throws Exception {
        var method = CoroutineTransformation.class.getDeclaredMethod("processIrreducibleCfg");
        method.setAccessible(true); method.invoke(transform);
    }

    private static int[] copiedMarkers(boolean complete, boolean heavyFirst) throws Exception {
        var program = copyCostProgram(heavyFirst);
        var graph = ProgramUtils.buildControlFlowGraph(program);
        if (!GraphUtils.isIrreducible(graph)) throw new AssertionError("copy-cost-control-reducible-input");
        var transform = costTransform(program);
        int originalCount = program.basicBlockCount();
        if (complete) {
            normalizeCost(transform);
        } else {
            int[] weights = new int[originalCount];
            for (int i = 0; i < originalCount; ++i) weights[i] = program.basicBlockAt(i).instructionCount();
            GraphUtils.splitIrreducibleGraph(graph, weights, transform.new SplittingBackend());
        }
        graph = ProgramUtils.buildControlFlowGraph(program);
        if (GraphUtils.isIrreducible(graph)) throw new AssertionError("copy-cost-control-not-normalized");
        int[] copied = new int[2];
        for (var block : program.getBasicBlocks()) {
            for (var phi : block.getPhis()) {
                var expected = new HashSet<Integer>();
                for (int predecessor : graph.incomingEdges(block.getIndex())) expected.add(predecessor);
                if (!sources(phi).equals(expected) || sources(phi).size() != phi.getIncomings().size()) {
                    throw new AssertionError("copy-cost-control-incomplete-phi");
                }
            }
            int marker = 0;
            for (var instruction : block) {
                if (instruction instanceof IntegerConstantInstruction) {
                    int value = ((IntegerConstantInstruction) instruction).getConstant();
                    if (value == 100 || value == 200) marker = value / 100;
                }
            }
            if (marker == 0) continue;
            boolean heavy = (marker == 1) == heavyFirst;
            String[] expected = heavy
                    ? new String[] {"java.lang.IllegalArgumentException", "java.lang.IllegalStateException",
                        "java.lang.Throwable"}
                    : new String[] {"java.lang.Throwable"};
            if (block.getTryCatchBlocks().size() != expected.length
                    || block.getPhis().size() != (heavy ? 3 : 1)) {
                throw new AssertionError("copy-cost-control-copied-metadata-lost");
            }
            for (int i = 0; i < expected.length; ++i) {
                var guard = block.getTryCatchBlocks().get(i);
                if (!expected[i].equals(guard.getExceptionType()) || guard.getHandler().getIndex() != 3) {
                    throw new AssertionError("copy-cost-control-handler-changed");
                }
            }
            if (block.getIndex() >= originalCount) ++copied[marker - 1];
        }
        return copied;
    }

    private static void copyCostControls() throws Exception {
        boolean decisionChanged = false;
        for (boolean heavyFirst : new boolean[] {false, true}) {
            int[] old = copiedMarkers(false, heavyFirst);
            int[] fixed = copiedMarkers(true, heavyFirst);
            int heavy = heavyFirst ? 0 : 1;
            int light = 1 - heavy;
            if (fixed[heavy] != 0 || fixed[light] != 1) {
                throw new AssertionError("copy-cost-control-heavy-domain-copied");
            }
            decisionChanged |= old[heavy] != fixed[heavy] || old[light] != fixed[light];
        }
        if (!decisionChanged) throw new AssertionError("copy-cost-control-no-real-decision-change");

        var reducible = new Program();
        var entry = reducible.createBasicBlock(); var exit = reducible.createBasicBlock();
        jump(entry, exit); exit.add(new ExitInstruction());
        String before = new ListingBuilder().buildListing(reducible, "");
        normalizeCost(costTransform(reducible));
        if (!before.equals(new ListingBuilder().buildListing(reducible, ""))
                || reducible.basicBlockCount() != 2 || reducible.basicBlockAt(0) != entry) {
            throw new AssertionError("copy-cost-control-reducible-fast-path-changed");
        }

        var overflow = copyCostProgram(true);
        var transform = costTransform(overflow);
        var initialize = CoroutineTransformation.class.getDeclaredMethod("initializeCopyWeights");
        initialize.setAccessible(true); initialize.invoke(transform);
        var total = CoroutineTransformation.class.getDeclaredField("totalCopyWeight");
        total.setAccessible(true); total.setInt(transform, Integer.MAX_VALUE);
        String original = new ListingBuilder().buildListing(overflow, "");
        try {
            transform.new SplittingBackend().split(new int[] {2}, new int[] {1});
            throw new AssertionError("copy-cost-control-overflow-not-refused");
        } catch (ArithmeticException expected) {
            if (!original.equals(new ListingBuilder().buildListing(overflow, ""))
                    || overflow.basicBlockCount() != 4 || total.getInt(transform) != Integer.MAX_VALUE) {
                throw new AssertionError("copy-cost-control-overflow-mutated-program");
            }
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("copy-cost")) {
            copyCostControls();
            System.out.println("{\"schemaVersion\":\"latent.java.coroutine-copy-cost-control.v1\","
                    + "\"cases\":[\"domain-choice\",\"reducible-parity\",\"overflow-before-copy\"],\"passed\":true}");
            return;
        }
        if (args.length != 1 || !(args[0].equals("original") || args[0].equals("corrected"))) {
            throw new IllegalArgumentException("coroutine-control-mode");
        }
        var program = new Program();
        var entry = program.createBasicBlock();
        var remaining = program.createBasicBlock();
        var header = program.createBasicBlock();
        var tail = program.createBasicBlock();
        var entryValue = program.createVariable();
        var current = program.createVariable();
        var increment = program.createVariable();
        var constant = new IntegerConstantInstruction(); constant.setReceiver(entryValue); entry.add(constant);
        branch(entry, entryValue, header, remaining);
        jump(remaining, header); branch(header, current, tail, remaining); jump(tail, header);
        var headerPhi = new Phi(); headerPhi.setReceiver(current);
        incoming(headerPhi, entry, entryValue);
        incoming(headerPhi, remaining, entryValue);
        incoming(headerPhi, tail, increment);
        header.getPhis().add(headerPhi);
        var tailPhi = new Phi(); tailPhi.setReceiver(increment);
        incoming(tailPhi, header, current); tail.getPhis().add(tailPhi);
        if (!GraphUtils.isIrreducible(ProgramUtils.buildControlFlowGraph(program))) {
            throw new AssertionError("coroutine-control-must-be-irreducible");
        }
        var transform = new CoroutineTransformation(null, Set.of(), true);
        Field field = CoroutineTransformation.class.getDeclaredField("program");
        field.setAccessible(true); field.set(transform, program);
        var copies = transform.new SplittingBackend().split(new int[] {remaining.getIndex()},
                new int[] {header.getIndex(), tail.getIndex()});
        var copiedHeader = program.basicBlockAt(copies[0]).getPhis().get(0);
        var copiedTail = program.basicBlockAt(copies[1]).getPhis().get(0);
        // Original external entry is retained only in the original loop.
        if (!sources(headerPhi).equals(Set.of(entry.getIndex(), tail.getIndex()))
                || !sources(tailPhi).equals(Set.of(header.getIndex()))) {
            throw new AssertionError("coroutine-control-original-loop-changed");
        }
        if (args[0].equals("original")) {
            if (!sources(copiedHeader).equals(Set.of(remaining.getIndex()))
                    || !copiedTail.getIncomings().isEmpty()) {
                throw new AssertionError("coroutine-control-unreviewed-original");
            }
        } else {
            if (!sources(copiedHeader).equals(Set.of(remaining.getIndex(), copies[1]))
                    || !sources(copiedTail).equals(Set.of(copies[0]))) {
                throw new AssertionError("coroutine-control-copied-loop-input-lost");
            }
            if (copiedHeader.getReceiver() != current || copiedTail.getReceiver() != increment
                    || copiedTail.getIncomings().get(0).getValue() != current) {
                throw new AssertionError("coroutine-control-values-changed");
            }
        }
        entryLiveness(args[0]);
        org.teavm.model.util.ArrayTypeCheck.check(args[0]);
        System.out.println("{\"schemaVersion\":\"latent.java.coroutine-phi-control.v1\",\"mode\":\""
                + args[0] + "\",\"passed\":true}");
    }
}

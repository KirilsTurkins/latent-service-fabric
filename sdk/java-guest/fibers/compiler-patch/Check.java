package org.teavm.backend.lowlevel.transform;

import java.lang.reflect.Field;
import java.util.HashSet;
import java.util.Set;
import org.teavm.common.GraphUtils;
import org.teavm.model.BasicBlock;
import org.teavm.model.Incoming;
import org.teavm.model.Phi;
import org.teavm.model.Program;
import org.teavm.model.Variable;
import org.teavm.model.MethodReference;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.instructions.JumpInstruction;
import org.teavm.model.instructions.BranchingCondition;
import org.teavm.model.instructions.BranchingInstruction;
import org.teavm.model.instructions.IntegerConstantInstruction;
import org.teavm.model.util.ProgramUtils;

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
        var awaited = new MethodReference("control.Await", "await", void.class);
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL); call.setMethod(awaited); entry.add(call);
        jump(entry, exit);
        var result = new ExitInstruction(); result.setValueToReturn(value); exit.add(result);
        var transform = new CoroutineTransformation(name -> null, Set.of(awaited), false);
        try {
            transform.apply(program, new MethodReference("control.Owner", "run", int.class));
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
        var pushInt = new MethodReference("org.teavm.runtime.Fiber", "push", int.class, void.class);
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

    public static void main(String[] args) throws Exception {
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
        System.out.println("{\"schemaVersion\":\"latent.java.coroutine-phi-control.v1\",\"mode\":\""
                + args[0] + "\",\"passed\":true}");
    }
}

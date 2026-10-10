package dev.latent.guest.runtime.compiler;

import org.teavm.model.BasicBlock;
import org.teavm.model.Program;
import org.teavm.model.instructions.JumpInstruction;

/** Follow the pinned low-level async processor's entry/body convention. The
 * coroutine backend splits block zero before consulting the original liveness
 * table, so operations that can suspend belong in the body, not that entry. */
final class ContinuationProgram {
    private ContinuationProgram() { }

    static BasicBlock body(Program program) {
        if (program.basicBlockCount() != 0)
            throw new IllegalStateException("continuation-program-already-has-blocks");
        var entry = program.createBasicBlock();
        var body = program.createBasicBlock();
        var jump = new JumpInstruction();
        jump.setTarget(body);
        entry.add(jump);
        return body;
    }
}

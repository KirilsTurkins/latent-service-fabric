package org.teavm.model.util;

import java.util.HashSet;
import java.util.Set;
import org.teavm.model.ClassHolder;
import org.teavm.model.MethodHolder;
import org.teavm.model.MethodReference;
import org.teavm.model.Program;
import org.teavm.model.ValueType;
import org.teavm.model.Variable;
import org.teavm.model.instructions.ArrayElementType;
import org.teavm.model.instructions.ExitInstruction;
import org.teavm.model.instructions.GetElementInstruction;
import org.teavm.model.instructions.IntegerConstantInstruction;
import org.teavm.model.instructions.InvocationType;
import org.teavm.model.instructions.InvokeInstruction;
import org.teavm.model.lowlevel.Characteristics;
import org.teavm.model.lowlevel.GCShadowStackContributor;

/** Execute the pinned type inference and real GC-root insertion on array-only edges. */
public final class ArrayTypeCheck {
    private static Variable element(Program program, Variable array, Variable index, ArrayElementType type) {
        var value = program.createVariable();
        var load = new GetElementInstruction(type);
        load.setArray(array); load.setIndex(index); load.setReceiver(value);
        program.basicBlockAt(0).add(load);
        return value;
    }

    private static void restoredArray(String mode) {
        var program = new Program(); var block = program.createBasicBlock();
        program.createVariable(); var array = program.createVariable();
        var index = program.createVariable();
        var zero = new IntegerConstantInstruction(); zero.setReceiver(index); block.add(zero);
        var fiber = program.createVariable();
        var current = new InvokeInstruction(); current.setType(InvocationType.SPECIAL);
        current.setMethod(new MethodReference("org.teavm.runtime.Fiber", "current",
                ValueType.object("org.teavm.runtime.Fiber")));
        current.setReceiver(fiber); block.add(current);
        // This is the real CoroutineTransformation.restoreVariable shape for arrays:
        // popObject writes back to the original array variable without a typed cast.
        var restore = new InvokeInstruction(); restore.setType(InvocationType.SPECIAL);
        restore.setMethod(new MethodReference("org.teavm.runtime.Fiber", "popObject",
                ValueType.object("java.lang.Object")));
        restore.setInstance(fiber); restore.setReceiver(array); block.add(restore);
        var scalar = element(program, array, index, ArrayElementType.INT);
        var call = new InvokeInstruction(); call.setType(InvocationType.SPECIAL);
        call.setMethod(new MethodReference("control.ArrayOwner", "safepoint", ValueType.VOID));
        block.add(call);
        var exit = new ExitInstruction(); exit.setValueToReturn(scalar); block.add(exit);
        var method = new MethodHolder("restored", ValueType.arrayOf(ValueType.INTEGER), ValueType.INTEGER);
        new ClassHolder("control.ArrayOwner").addMethod(method); method.setProgram(program);
        var inferer = new TypeInferer(); inferer.inferTypes(program, method.getReference());
        boolean original = mode.equals("original");
        if (inferer.typeOf(scalar.getIndex()) != (original ? VariableType.OBJECT : VariableType.INT)) {
            throw new AssertionError("array-control-restored-primitive-type-lost");
        }
        new GCShadowStackContributor(new Characteristics(name -> null)).contribute(program, method);
        boolean scalarRoot = false;
        for (var instruction : block) {
            if (instruction instanceof InvokeInstruction) {
                var invoke = (InvokeInstruction) instruction;
                if (invoke.getMethod().getClassName().equals("org.teavm.runtime.ShadowStack")
                        && invoke.getMethod().getName().equals("registerGCRoot")
                        && invoke.getArguments().get(1) == scalar) {
                    scalarRoot = true;
                }
            }
        }
        if (scalarRoot != original) throw new AssertionError("array-control-restored-scalar-root");
    }

    public static void check(String mode) {
        var program = new Program();
        var block = program.createBasicBlock();
        program.createVariable();
        var ints = program.createVariable();
        var objects = program.createVariable();
        var matrix = program.createVariable();
        var index = program.createVariable();
        var zero = new IntegerConstantInstruction(); zero.setReceiver(index); block.add(zero);
        var scalar = element(program, ints, index, ArrayElementType.INT);
        var object = element(program, objects, index, ArrayElementType.OBJECT);
        var row = element(program, matrix, index, ArrayElementType.OBJECT);
        var nested = element(program, row, index, ArrayElementType.INT);
        var call = new InvokeInstruction();
        call.setType(InvocationType.SPECIAL);
        call.setMethod(new MethodReference("control.ArrayOwner", "safepoint", ValueType.VOID));
        block.add(call);
        // All four loaded values remain live across the preceding real call instruction.
        var consume = new InvokeInstruction(); consume.setType(InvocationType.SPECIAL);
        consume.setMethod(new MethodReference("control.ArrayOwner", "consume", ValueType.INTEGER,
                ValueType.object("java.lang.Object"), ValueType.arrayOf(ValueType.INTEGER),
                ValueType.INTEGER, ValueType.VOID));
        consume.setArguments(scalar, object, row, nested); block.add(consume);
        block.add(new ExitInstruction());
        var method = new MethodHolder("run", ValueType.arrayOf(ValueType.INTEGER),
                ValueType.arrayOf(ValueType.object("java.lang.Object")),
                ValueType.arrayOf(ValueType.arrayOf(ValueType.INTEGER)), ValueType.VOID);
        new ClassHolder("control.ArrayOwner").addMethod(method); method.setProgram(program);
        var inferer = new TypeInferer(); inferer.inferTypes(program, method.getReference());
        boolean original = mode.equals("original");
        if (inferer.typeOf(scalar.getIndex()) != (original ? VariableType.OBJECT : VariableType.INT)
                || inferer.typeOf(object.getIndex()) != VariableType.OBJECT
                || inferer.typeOf(row.getIndex()) != (original ? VariableType.OBJECT : VariableType.INT_ARRAY)
                || inferer.typeOf(nested.getIndex()) != (original ? VariableType.OBJECT : VariableType.INT)) {
            throw new AssertionError("array-control-unreviewed-type-inference");
        }
        new GCShadowStackContributor(new Characteristics(name -> null)).contribute(program, method);
        var roots = new HashSet<Variable>();
        for (var instruction : block) {
            if (instruction instanceof InvokeInstruction) {
                var invoke = (InvokeInstruction) instruction;
                if (invoke.getMethod().getClassName().equals("org.teavm.runtime.ShadowStack")
                        && invoke.getMethod().getName().equals("registerGCRoot")) {
                    if (invoke.getArguments().size() != 2) throw new AssertionError("array-control-root-shape");
                    roots.add(invoke.getArguments().get(1));
                }
            }
        }
        var expected = original ? Set.of(scalar, object, row, nested) : Set.of(object, row);
        if (!roots.equals(expected)) {
            throw new AssertionError("array-control-primitive-root-or-reference-root-lost");
        }
        restoredArray(mode);
    }
}

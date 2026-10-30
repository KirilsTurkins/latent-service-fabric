"""Exact TeaVM 0.15 coroutine repairs in a private compiler JAR, never its cache."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import zipfile

from tools.rust_capsule_project import read_file

UPSTREAM_SHA256 = '5fb6d1c6e33fb4418239ec4c3cb93435b194bf5b3d36e8350836e2830567ba8c'
BEFORE = 'phi.getIncomings().removeIf(incoming -> !domainSet.contains(incoming.getSource().getIndex()));'
AFTER = ('phi.getIncomings().removeIf(incoming -> !domainSet.contains(incoming.getSource().getIndex())\n'
         '                            && !copiedSet.contains(incoming.getSource().getIndex()));')
DOMAIN = 'var domainSet = IntHashSet.from(remaining);'
COPIED_DOMAIN = DOMAIN + '\n            var copiedSet = IntHashSet.from(copies);'
LIVENESS_REPLACEMENTS = (
    ('processBlock(program.basicBlockAt(i));',
     'processBlock(program.basicBlockAt(i), i == basicBlockCount ? 0 : i);'),
    ('private void processBlock(BasicBlock block) {',
     'private void processBlock(BasicBlock block, int originalIndex) {'),
    ('collectSplitInstructions(block);', 'collectSplitInstructions(block, originalIndex);'),
    ('private Map<Instruction, BitSet> collectSplitInstructions(BasicBlock block) {',
     'private Map<Instruction, BitSet> collectSplitInstructions(BasicBlock block, int originalIndex) {'),
    ('livenessAnalysis.liveOut(block.getIndex());', 'livenessAnalysis.liveOut(originalIndex);'),
)
# Preserve the immutable upstream source. Only this exact private derivation
# changes the split objective; the graph algorithm and all old repairs remain.
COPY_COST_FIELDS = '''    private List<Integer> copyWeights;
    private int totalCopyWeight;
'''
COPY_COST_HELPERS = '''    private static int structuralCopyCost(BasicBlock block) {
        // Count the complete initial IR payload copied by copyBasicBlock.
        // These are structural units, never predicted machine bytes or time.
        int result = Math.addExact(1, block.instructionCount());
        result = Math.addExact(result, block.getPhis().size());
        for (var phi : block.getPhis()) {
            result = Math.addExact(result, phi.getIncomings().size());
        }
        result = Math.addExact(result, block.getTryCatchBlocks().size());
        return Math.addExact(result, block.getExceptionVariable() == null ? 0 : 1);
    }

    private int[] initializeCopyWeights() {
        int[] result = new int[program.basicBlockCount()];
        var tracked = new ArrayList<Integer>(result.length);
        int total = 0;
        for (int i = 0; i < result.length; ++i) {
            int weight = structuralCopyCost(program.basicBlockAt(i));
            total = Math.addExact(total, weight);
            result[i] = weight;
            tracked.add(weight);
        }
        copyWeights = tracked;
        totalCopyWeight = total;
        return result;
    }

    private int checkedCopiedTotal(int[] toCopy) {
        if (copyWeights == null) {
            initializeCopyWeights();
        }
        if (copyWeights.size() != program.basicBlockCount()) {
            throw new IllegalStateException("coroutine-copy-cost-node-drift");
        }
        int additional = 0;
        for (int node : toCopy) {
            additional = Math.addExact(additional, copyWeights.get(node));
        }
        // The unchanged splitter's nonnegative domain/collapse sums represent
        // subsets of these real-node weights. Admit every clone before it
        // exists, keeping their checked global sum within int throughout.
        return Math.addExact(totalCopyWeight, additional);
    }

'''
COPY_COST_REPLACEMENTS = (
    ('    private ValueType returnType;\n',
     '    private ValueType returnType;\n' + COPY_COST_FIELDS),
    ('    private void processIrreducibleCfg() {\n',
     COPY_COST_HELPERS + '    private void processIrreducibleCfg() {\n'
     '        copyWeights = null;\n        totalCopyWeight = 0;\n'),
    ('''        int[] weights = new int[graph.size()];
        for (int i = 0; i < program.basicBlockCount(); ++i) {
            weights[i] = program.basicBlockAt(i).instructionCount();
        }''', '''        int[] weights = initializeCopyWeights();'''),
    ('        public int[] split(int[] remaining, int[] toCopy) {\n',
     '        public int[] split(int[] remaining, int[] toCopy) {\n'
     '            int checkedTotal = checkedCopiedTotal(toCopy);\n'),
    ('''                ProgramUtils.copyBasicBlock(block, blockCopy);
                copies[i] = blockCopy.getIndex();''',
     '''                ProgramUtils.copyBasicBlock(block, blockCopy);
                if (blockCopy.getIndex() != copyWeights.size()) {
                    throw new IllegalStateException("coroutine-copy-cost-copy-drift");
                }
                // Keep the same initial weight inherited by the splitter,
                // even after predecessor pruning changes the copied PHIs.
                copyWeights.add(copyWeights.get(node));
                copies[i] = blockCopy.getIndex();'''),
    ('            return copies;\n',
     '            totalCopyWeight = checkedTotal;\n            return copies;\n'),
)
# Default-off, fixed public-source observation; never selects production weights.
COPY_OBSERVER_PROPERTY = 'latent.java.coroutine.public-copy-cost.v1'
COPY_OBSERVER_TOKEN = '6a2f7a5a13b3295761b0f18989e47cc7ff106a7c9546c559492247fcd36430c8:14c7bb47a7634153b4dcf39473a31f7f87f971f8c90a602b378be498dc938236'
COPY_OBSERVER_FIELDS = '''    private java.security.MessageDigest observedDecisions;
    private int observedSplitCalls;
    private int observedCopiedNodes;
    private int observedTraceNodes;
    private static int publicObservationCount;
'''
COPY_OBSERVER_HELPERS = r'''    private static java.security.MessageDigest copyDecisionDigest() {
        try {
            return java.security.MessageDigest.getInstance("SHA-256");
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException("coroutine-copy-observer-sha256", e);
        }
    }

    private void observeInteger(int value) {
        observedDecisions.update((byte) (value >>> 24));
        observedDecisions.update((byte) (value >>> 16));
        observedDecisions.update((byte) (value >>> 8));
        observedDecisions.update((byte) value);
    }

    private void observeSplit(int[] remaining, int[] toCopy) {
        if (observedDecisions == null) {
            return;
        }
        observedSplitCalls = Math.addExact(observedSplitCalls, 1);
        observedCopiedNodes = Math.addExact(observedCopiedNodes, toCopy.length);
        observedTraceNodes = Math.addExact(observedTraceNodes,
                Math.addExact(remaining.length, toCopy.length));
        if (observedSplitCalls > 65536 || observedTraceNodes > 1048576
                || observedCopiedNodes > 1048576) {
            throw new IllegalStateException("coroutine-copy-observer-trace-bound");
        }
        observeInteger(remaining.length);
        for (int node : remaining) {
            observeInteger(node);
        }
        observeInteger(toCopy.length);
        for (int node : toCopy) {
            observeInteger(node);
        }
    }

    private static String observedHex(byte[] bytes) {
        var result = new StringBuilder(64);
        for (byte value : bytes) {
            result.append(Character.forDigit((value >>> 4) & 15, 16));
            result.append(Character.forDigit(value & 15, 16));
        }
        return result.toString();
    }

    private static synchronized void claimPublicObservation() {
        if (++publicObservationCount != 1) {
            throw new IllegalStateException("coroutine-copy-observer-ambiguous");
        }
    }

    private boolean observePublicCopyCost(MethodReference method) {
        if (!"__COPY_OBSERVER_TOKEN__".equals(System.getProperty(
                "latent.java.coroutine.public-copy-cost.v1"))) {
            return false;
        }
        if (!method.getClassName().equals("dev.latent.app.Capsule") || !method.getName().equals("pools")) {
            return false;
        }
        if (method.parameterCount() != 0 || !method.getReturnType().equals(ValueType.object("java.lang.Long"))) {
            throw new IllegalStateException("coroutine-copy-observer-method-shape");
        }
        claimPublicObservation();
        int blocks = program.basicBlockCount();
        if (blocks > 65536 || program.variableCount() > 262144) {
            throw new IllegalStateException("coroutine-copy-observer-input-bound");
        }
        int instructions = 0;
        int phis = 0;
        int incoming = 0;
        int handlers = 0;
        int exceptions = 0;
        int structural = 0;
        for (var block : program.getBasicBlocks()) {
            instructions = Math.addExact(instructions, block.instructionCount());
            phis = Math.addExact(phis, block.getPhis().size());
            for (var phi : block.getPhis()) {
                incoming = Math.addExact(incoming, phi.getIncomings().size());
            }
            handlers = Math.addExact(handlers, block.getTryCatchBlocks().size());
            exceptions = Math.addExact(exceptions, block.getExceptionVariable() == null ? 0 : 1);
            structural = Math.addExact(structural, structuralCopyCost(block));
        }
        if (structural > 1048576) {
            throw new IllegalStateException("coroutine-copy-observer-input-bound");
        }
        // Copy the actual post-resume-split, pre-normalization Program once.
        // Run the SAME splitter and corrected PHI backend, not a graph model.
        var old = new CoroutineTransformation(classSource, asyncMethods, hasThreads);
        old.program = ProgramUtils.copy(program);
        old.observedDecisions = copyDecisionDigest();
        var oldGraph = ProgramUtils.buildControlFlowGraph(old.program);
        boolean irreducible = GraphUtils.isIrreducible(oldGraph);
        if (irreducible) {
            old.initializeCopyWeights(); // Conservative global safety bound on copies.
            int[] oldWeights = new int[blocks];
            for (int i = 0; i < blocks; ++i) {
                oldWeights[i] = old.program.basicBlockAt(i).instructionCount();
            }
            GraphUtils.splitIrreducibleGraph(oldGraph, oldWeights, old.new SplittingBackend());
        }
        observedDecisions = copyDecisionDigest();
        observedSplitCalls = observedCopiedNodes = observedTraceNodes = 0;
        processIrreducibleCfg();
        String oldDigest = observedHex(old.observedDecisions.digest());
        String newDigest = observedHex(observedDecisions.digest());
        observedDecisions = null;
        System.err.println("latent.java.coroutine-copy-observation.v1 {"
                + "\"schemaVersion\":\"latent.java.coroutine-copy-observation.v1\","
                + "\"hookCount\":1,\"blocks\":" + blocks
                + ",\"instructions\":" + instructions + ",\"phis\":" + phis
                + ",\"incomings\":" + incoming + ",\"handlers\":" + handlers
                + ",\"exceptionBindings\":" + exceptions + ",\"structuralWeight\":" + structural
                + ",\"irreducible\":" + irreducible
                + ",\"oldSplitCalls\":" + old.observedSplitCalls + ",\"newSplitCalls\":" + observedSplitCalls
                + ",\"oldCopiedNodes\":" + old.observedCopiedNodes + ",\"newCopiedNodes\":" + observedCopiedNodes
                + ",\"oldFinalBlocks\":" + old.program.basicBlockCount()
                + ",\"newFinalBlocks\":" + program.basicBlockCount()
                + ",\"oldFinalWeight\":" + old.totalCopyWeight + ",\"newFinalWeight\":" + totalCopyWeight
                + ",\"oldDecisionSha256\":\"" + oldDigest + "\",\"newDecisionSha256\":\"" + newDigest + "\"}");
        return true;
    }

'''.replace('__COPY_OBSERVER_TOKEN__', COPY_OBSERVER_TOKEN)
COPY_OBSERVER_REPLACEMENTS = (
    (COPY_COST_FIELDS, COPY_COST_FIELDS + COPY_OBSERVER_FIELDS),
    ('        processIrreducibleCfg();\n        RedundantJumpElimination.optimize(program);',
     '        if (!observePublicCopyCost(methodReference)) {\n            processIrreducibleCfg();\n        }\n        RedundantJumpElimination.optimize(program);'),
    (COPY_COST_HELPERS, COPY_COST_HELPERS + COPY_OBSERVER_HELPERS),
    ('            int checkedTotal = checkedCopiedTotal(toCopy);\n',
     '            int checkedTotal = checkedCopiedTotal(toCopy);\n            observeSplit(remaining, toCopy);\n'),
)
TYPE_INFERER_SHA256 = 'a1139fea2ab16d6b520e6c975f5fb04f9a54077269c811ee9853bf301db8489d'
TYPE_SEED_BEFORE = 'if (types[i] != null && graph.outgoingEdgesCount(i) > 0) {'
TYPE_SEED_AFTER = ('if (types[i] != null && (graph.outgoingEdgesCount(i) > 0\n'
                   '                    || arrayElemGraph.outgoingEdgesCount(i) > 0)) {')
TYPE_ELEMENT_BEFORE = '''        public void getElement(VariableReader receiver, VariableReader array, VariableReader index,
                ArrayElementType type) {
            arrayElemBuilder.addEdge(array.getIndex(), receiver.getIndex());
        }'''
TYPE_ELEMENT_AFTER = '''        public void getElement(VariableReader receiver, VariableReader array, VariableReader index,
                ArrayElementType type) {
            switch (type) {
                case OBJECT:
                    arrayElemBuilder.addEdge(array.getIndex(), receiver.getIndex());
                    break;
                case BYTE:
                case SHORT:
                case CHAR:
                case INT:
                    types[receiver.getIndex()] = new InferenceType(InferenceKind.INT, 0);
                    break;
                case LONG:
                    types[receiver.getIndex()] = new InferenceType(InferenceKind.LONG, 0);
                    break;
                case FLOAT:
                    types[receiver.getIndex()] = new InferenceType(InferenceKind.FLOAT, 0);
                    break;
                case DOUBLE:
                    types[receiver.getIndex()] = new InferenceType(InferenceKind.DOUBLE, 0);
                    break;
                default:
                    throw new AssertionError(type);
            }
        }'''
CLASS_ROOT = 'org/teavm/backend/lowlevel/transform/'
COROUTINE_CLASSES = frozenset(CLASS_ROOT + name for name in (
    'CoroutineTransformation.class', 'CoroutineTransformation$1.class',
    'CoroutineTransformation$SplittingBackend.class'))
TYPE_ROOT = 'org/teavm/model/util/'
ASYNC_SOURCE_SHA256 = '510b04fa6db5c0a47dc9656643bb3b1af0a104ed66cfb32786b88f93bbb4740d'
ASYNC_CLASSES = frozenset(TYPE_ROOT + name for name in (
    'AsyncMethodFinder.class', 'AsyncMethodFinder$CallStack.class',
    'AsyncMethodFinder$AsyncInstructionReader.class'))
MONITOR_CONTROL = 'org/teavm/dependency/MonitorAsyncControl.class'
MONITOR_CONTROLS = frozenset((MONITOR_CONTROL, 'org/teavm/dependency/MonitorAsyncControl$Inputs.class'))
ASYNC_BEFORE = '''    private boolean findAsyncMethods() {
        boolean result = false;
        loop: for (String clsName : classSource.getClassNames()) {
            ClassReader cls = classSource.get(clsName);
            for (MethodReader method : cls.getMethods()) {
                if (!asyncMethods.contains(method.getReference()) || method.getProgram() == null) {
                    continue;
                }
                if (hasMonitor(method)) {
                    result = true;
                    break loop;
                }
            }
        }
        boolean hasThreads = dependency.getReachableMethods().contains(new MethodReference(
                Thread.class, "start", void.class));
        return result && hasThreads;
    }

'''
ASYNC_AFTER = '''    private boolean findAsyncMethods() {
        // Monitor entry can suspend whenever a real Java Thread.start is reachable.
        // At this point asyncMethods is still empty: annotation roots are added
        // by find() afterwards, so scanning it here cannot discover contention.
        return dependency.getReachableMethods().contains(new MethodReference(
                Thread.class, "start", void.class));
    }
'''

CHECKPOINT_FIND_BEFORE = '''        this.classSource = classSource;
        hasAsyncMethods = findAsyncMethods();'''
CHECKPOINT_FIND_AFTER = '''        this.classSource = classSource;
        validateCheckpointCallers();
        hasAsyncMethods = findAsyncMethods();'''
CHECKPOINT_VALIDATION = '''    private void validateCheckpointCallers() {
        // CTarget calls find after every dependency completion callback, before
        // coroutine transformation. This closure deliberately ignores asyncMethods.
        MethodReference checkpoint = new MethodReference("dev.latent.guest.runtime.Activation",
                "checkpoint", org.teavm.model.ValueType.VOID);
        MethodReference managedEntry = new MethodReference(Fiber.class, "start", void.class);
        if (!dependency.getReachableMethods().contains(checkpoint)) {
            return;
        }
        CallGraphNode root = callGraph.getNode(checkpoint);
        if (root == null) {
            System.err.println("latent.java.checkpoint-site.v1 root");
            throw checkpointRefusal("java-checkpoint-unresolved-741");
        }
        Set<MethodReference> visited = new HashSet<>();
        List<CallGraphNode> pending = new ArrayList<>();
        visited.add(checkpoint);
        pending.add(root);
        int edges = 0;
        for (int index = 0; index < pending.size(); ++index) {
            CallGraphNode node = pending.get(index);
            MethodReference reference = node.getMethod();
            ClassReader cls = reference == null ? null : classSource.get(reference.getClassName());
            MethodReader method = cls == null ? null : cls.getMethod(reference.getDescriptor());
            if (method == null) {
                System.err.println("latent.java.checkpoint-site.v1 method");
                throw checkpointRefusal("java-checkpoint-unresolved-741");
            }
            if (reference.getName().equals("<clinit>")
                    || method.getAnnotations().get("org.teavm.interop.Unmanaged") != null
                    || cls.getAnnotations().get("org.teavm.interop.Unmanaged") != null) {
                throw checkpointRefusal("java-checkpoint-nonsuspendable-context-741");
            }
            // Pinned Fiber.start() installs current=this before runner.run() and
            // restores its former value afterward. Callers are outside that new
            // managed context. No other method/overload or async label is a barrier.
            if (reference.equals(managedEntry)
                    && method.getLevel() == org.teavm.model.AccessLevel.PRIVATE
                    && !method.hasModifier(ElementModifier.STATIC)) {
                if (!pinnedFiberEntry(method)) {
                    System.err.println("latent.java.checkpoint-site.v1 managed-entry");
                    throw checkpointRefusal("java-checkpoint-unresolved-741");
                }
                continue;
            }
            for (CallSite site : node.getCallerCallSites()) {
                if (++edges > 262144) {
                    throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                }
                for (CallGraphNode caller : site.getCallers()) {
                    if (++edges > 262144) {
                        throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                    }
                    if (caller == null || caller.getMethod() == null) {
                        System.err.println("latent.java.checkpoint-site.v1 caller");
                        throw checkpointRefusal("java-checkpoint-unresolved-741");
                    }
                    if (!visited.contains(caller.getMethod())) {
                        if (pending.size() == 65536) {
                            throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                        }
                        visited.add(caller.getMethod());
                        pending.add(caller);
                    }
                }
            }
        }
    }

    private boolean pinnedFiberEntry(MethodReader method) {
        // Never resolve this baseline through an application classpath. Both
        // host classes must come from the same authenticated compiler JAR,
        // whose nonreplacement entries the owned compiler recipe preserves.
        int stage = 1;
        try {
            if (Fiber.class.getClassLoader() != AsyncMethodFinder.class.getClassLoader()) {
                return fiberEntryRefusal(stage);
            }
            java.nio.file.Path jar = java.nio.file.Path.of(Fiber.class.getProtectionDomain()
                    .getCodeSource().getLocation().toURI()).toRealPath();
            java.nio.file.Path finderJar = java.nio.file.Path.of(AsyncMethodFinder.class
                    .getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
            if (!jar.equals(finderJar) || !java.nio.file.Files.isRegularFile(jar,
                    java.nio.file.LinkOption.NOFOLLOW_LINKS) || java.nio.file.Files.size(jar) > 67108864) {
                return fiberEntryRefusal(stage);
            }
            stage = 2;
            try (java.util.zip.ZipFile zip = new java.util.zip.ZipFile(jar.toFile())) {
                java.util.zip.ZipEntry entry = zip.getEntry("org/teavm/runtime/Fiber.class");
                if (entry == null || entry.getSize() <= 0 || entry.getSize() > 131072) {
                    return fiberEntryRefusal(stage);
                }
            }
            try (org.teavm.parsing.resource.ResourceProvider provider =
                    org.teavm.parsing.resource.ResourceProvider.ofClassPath(
                            Collections.singletonList(jar.toFile()))) {
                // Match TeaVMTool's pinned nonincremental production source pass.
                org.teavm.model.ClassHolderSource pinnedSource = new org.teavm.model.PreOptimizingClassHolderSource(
                        new org.teavm.parsing.resource.ResourceBytecodeClassHolderSource(
                                provider, new org.teavm.model.ReferenceCache()));
                org.teavm.model.ClassHolder pinned = pinnedSource.get(Fiber.class.getName());
                org.teavm.model.MethodHolder expected = pinned == null ? null : pinned.getMethod(method.getDescriptor());
                stage = 3;
                if (expected == null || expected.getLevel() != org.teavm.model.AccessLevel.PRIVATE
                        || expected.hasModifier(ElementModifier.STATIC)) {
                    return fiberEntryRefusal(stage);
                }
                for (ElementModifier modifier : ElementModifier.values()) {
                    if (method.hasModifier(modifier) != expected.hasModifier(modifier)) {
                        return fiberEntryRefusal(stage);
                    }
                }
                stage = 2;
                // DependencyClassSource's pinned normal program-supplier pass.
                // Resolve only against this same authenticated compiler JAR,
                // never dependency/application class sources or host resources.
                org.teavm.diagnostics.AccumulationDiagnostics diagnostics =
                        new org.teavm.diagnostics.AccumulationDiagnostics();
                org.teavm.dependency.ReferenceResolver resolver = new org.teavm.dependency.ReferenceResolver(
                        pinnedSource, new String[] { org.teavm.interop.Platforms.C,
                                org.teavm.interop.Platforms.LOW_LEVEL, org.teavm.interop.Platforms.OWN_GC }, diagnostics);
                org.teavm.model.Program program = expected.getProgram();
                if (program == null) {
                    return fiberEntryRefusal(stage);
                }
                resolver.use(expected.getReference());
                resolver.resolve(expected, program);
                if (!diagnostics.getSevereProblems().isEmpty()) {
                    return fiberEntryRefusal(stage);
                }
                new org.teavm.model.transformation.ClassInitInsertion(pinnedSource).apply(expected, program);
                stage = 4;
                return sameFiberEntryBody(program, method.getProgram()) || fiberEntryRefusal(stage);
            }
        } catch (Exception failure) {
            return fiberEntryRefusal(stage); // Unavailable proof cannot establish a context boundary.
        }
    }

    private boolean fiberEntryRefusal(int stage) {
        // Four fixed compiler-owned categories; no paths, names, IR or exception text.
        System.err.println("latent.java.checkpoint-entry.v1 " + stage);
        return false;
    }

    private org.teavm.model.Program boundedFiberEntryBody(ProgramReader program) {
        if (program == null || program.variableCount() <= 0 || program.variableCount() > 128
                || program.basicBlockCount() <= 0 || program.basicBlockCount() > 64) {
            return null;
        }
        int instructions = 0, phis = 0;
        for (int index = 0; index < program.basicBlockCount(); ++index) {
            org.teavm.model.BasicBlockReader block = program.basicBlockAt(index);
            // The pinned private entry has no exceptional control-flow region.
            // Any added handler or exception receiver must refuse, never disappear
            // from a pretty-printed body comparison.
            if (block == null || block.getExceptionVariable() != null || !block.readTryCatchBlocks().isEmpty()) {
                return null;
            }
            for (org.teavm.model.PhiReader phi : block.readPhis()) {
                if (++phis > 128 || phi.readIncomings().size() > 64) {
                    return null;
                }
            }
            org.teavm.model.InstructionIterator iterator = block.iterateInstructions();
            while (iterator.hasNext()) {
                iterator.next();
                if (++instructions > 256) {
                    return null;
                }
            }
        }
        return org.teavm.model.util.ProgramUtils.copy(program);
    }

    private boolean sameFiberVariable(VariableReader first, VariableReader second) {
        return first == null ? second == null : second != null && first.getIndex() == second.getIndex();
    }

    private boolean sameFiberEntryBody(ProgramReader expectedReader, ProgramReader actualReader) {
        org.teavm.model.Program expected = boundedFiberEntryBody(expectedReader);
        org.teavm.model.Program actual = boundedFiberEntryBody(actualReader);
        if (expected == null || actual == null || expected.variableCount() != actual.variableCount()
                || expected.basicBlockCount() != actual.basicBlockCount()) {
            return false;
        }
        for (int index = 0; index < expected.basicBlockCount(); ++index) {
            org.teavm.model.BasicBlock first = expected.basicBlockAt(index), second = actual.basicBlockAt(index);
            if (first.getPhis().size() != second.getPhis().size()) {
                return false;
            }
            for (int phiIndex = 0; phiIndex < first.getPhis().size(); ++phiIndex) {
                org.teavm.model.Phi left = first.getPhis().get(phiIndex), right = second.getPhis().get(phiIndex);
                if (!sameFiberVariable(left.getReceiver(), right.getReceiver())
                        || left.getIncomings().size() != right.getIncomings().size()) {
                    return false;
                }
                for (int incomingIndex = 0; incomingIndex < left.getIncomings().size(); ++incomingIndex) {
                    org.teavm.model.Incoming leftIncoming = left.getIncomings().get(incomingIndex);
                    org.teavm.model.Incoming rightIncoming = right.getIncomings().get(incomingIndex);
                    if (leftIncoming.getSource().getIndex() != rightIncoming.getSource().getIndex()
                            || !sameFiberVariable(leftIncoming.getValue(), rightIncoming.getValue())) {
                        return false;
                    }
                }
            }
            java.util.Iterator<org.teavm.model.Instruction> left = first.iterator(), right = second.iterator();
            while (left.hasNext() && right.hasNext()) {
                if (!sameFiberInstruction(left.next(), right.next())) {
                    return false;
                }
            }
            if (left.hasNext() || right.hasNext()) {
                return false;
            }
        }
        return true;
    }

    private boolean sameFiberInstruction(org.teavm.model.Instruction first, org.teavm.model.Instruction second) {
        if (first.getClass() != second.getClass()) {
            return false;
        }
        if (first instanceof org.teavm.model.instructions.EmptyInstruction) {
            // The pinned preoptimized body retains operandless NOPs. Their
            // concrete type, position and count remain part of exact equality.
            return true;
        } else if (first instanceof org.teavm.model.instructions.InitClassInstruction) {
            return ((org.teavm.model.instructions.InitClassInstruction) first).getClassName().equals(
                    ((org.teavm.model.instructions.InitClassInstruction) second).getClassName());
        } else if (first instanceof org.teavm.model.instructions.GetFieldInstruction) {
            org.teavm.model.instructions.GetFieldInstruction left =
                    (org.teavm.model.instructions.GetFieldInstruction) first;
            org.teavm.model.instructions.GetFieldInstruction right =
                    (org.teavm.model.instructions.GetFieldInstruction) second;
            return left.getField().equals(right.getField()) && left.getFieldType().equals(right.getFieldType())
                    && sameFiberVariable(left.getInstance(), right.getInstance())
                    && sameFiberVariable(left.getReceiver(), right.getReceiver());
        } else if (first instanceof org.teavm.model.instructions.PutFieldInstruction) {
            org.teavm.model.instructions.PutFieldInstruction left =
                    (org.teavm.model.instructions.PutFieldInstruction) first;
            org.teavm.model.instructions.PutFieldInstruction right =
                    (org.teavm.model.instructions.PutFieldInstruction) second;
            return left.getField().equals(right.getField()) && left.getFieldType().equals(right.getFieldType())
                    && sameFiberVariable(left.getInstance(), right.getInstance())
                    && sameFiberVariable(left.getValue(), right.getValue());
        } else if (first instanceof org.teavm.model.instructions.InvokeInstruction) {
            org.teavm.model.instructions.InvokeInstruction left = (org.teavm.model.instructions.InvokeInstruction) first;
            org.teavm.model.instructions.InvokeInstruction right = (org.teavm.model.instructions.InvokeInstruction) second;
            if (!left.getMethod().equals(right.getMethod()) || left.getType() != right.getType()
                    || !sameFiberVariable(left.getInstance(), right.getInstance())
                    || !sameFiberVariable(left.getReceiver(), right.getReceiver())
                    || left.getArguments().size() != right.getArguments().size()) {
                return false;
            }
            for (int index = 0; index < left.getArguments().size(); ++index) {
                if (!sameFiberVariable(left.getArguments().get(index), right.getArguments().get(index))) {
                    return false;
                }
            }
            return true;
        } else if (first instanceof org.teavm.model.instructions.AssignInstruction) {
            org.teavm.model.instructions.AssignInstruction left = (org.teavm.model.instructions.AssignInstruction) first;
            org.teavm.model.instructions.AssignInstruction right = (org.teavm.model.instructions.AssignInstruction) second;
            return sameFiberVariable(left.getAssignee(), right.getAssignee())
                    && sameFiberVariable(left.getReceiver(), right.getReceiver());
        } else if (first instanceof org.teavm.model.instructions.IntegerConstantInstruction) {
            org.teavm.model.instructions.IntegerConstantInstruction left =
                    (org.teavm.model.instructions.IntegerConstantInstruction) first;
            org.teavm.model.instructions.IntegerConstantInstruction right =
                    (org.teavm.model.instructions.IntegerConstantInstruction) second;
            return left.getConstant() == right.getConstant()
                    && sameFiberVariable(left.getReceiver(), right.getReceiver());
        } else if (first instanceof org.teavm.model.instructions.BinaryInstruction) {
            org.teavm.model.instructions.BinaryInstruction left = (org.teavm.model.instructions.BinaryInstruction) first;
            org.teavm.model.instructions.BinaryInstruction right = (org.teavm.model.instructions.BinaryInstruction) second;
            return left.getOperation() == right.getOperation() && left.getOperandType() == right.getOperandType()
                    && sameFiberVariable(left.getReceiver(), right.getReceiver())
                    && sameFiberVariable(left.getFirstOperand(), right.getFirstOperand())
                    && sameFiberVariable(left.getSecondOperand(), right.getSecondOperand());
        } else if (first instanceof org.teavm.model.instructions.BranchingInstruction) {
            org.teavm.model.instructions.BranchingInstruction left = (org.teavm.model.instructions.BranchingInstruction) first;
            org.teavm.model.instructions.BranchingInstruction right = (org.teavm.model.instructions.BranchingInstruction) second;
            return left.getCondition() == right.getCondition() && sameFiberVariable(left.getOperand(), right.getOperand())
                    && left.getConsequent().getIndex() == right.getConsequent().getIndex()
                    && left.getAlternative().getIndex() == right.getAlternative().getIndex();
        } else if (first instanceof org.teavm.model.instructions.JumpInstruction) {
            return ((org.teavm.model.instructions.JumpInstruction) first).getTarget().getIndex()
                    == ((org.teavm.model.instructions.JumpInstruction) second).getTarget().getIndex();
        } else if (first instanceof org.teavm.model.instructions.ExitInstruction) {
            return sameFiberVariable(((org.teavm.model.instructions.ExitInstruction) first).getValueToReturn(),
                    ((org.teavm.model.instructions.ExitInstruction) second).getValueToReturn());
        }
        return false; // No unknown instruction or incomplete representation can establish this barrier.
    }

    private IllegalStateException checkpointRefusal(String reason) {
        // Static owned reason only: never print application/call-graph details.
        System.err.println("latent.java.checkpoint-context.v1 " + reason);
        return new IllegalStateException(reason);
    }

'''

TYPE_CLASSES = frozenset(TYPE_ROOT + name for name in (
    'TypeInferer.class', 'TypeInferer$1.class', 'TypeInferer$2.class',
    'TypeInferer$InferenceKind.class', 'TypeInferer$InferenceType.class'))
PATCH_CLASSES = COROUTINE_CLASSES | TYPE_CLASSES | ASYNC_CLASSES
CONTROL = CLASS_ROOT + 'Check.class'
ARRAY_CONTROL = TYPE_ROOT + 'ArrayTypeCheck.class'
CONTROLS = frozenset((CONTROL, ARRAY_CONTROL)) | MONITOR_CONTROLS
MAX_JAR_BYTES = 64 * 1024 * 1024
RELOCATED_IMPORTS = ('IntHashSet', 'IntIntHashMap', 'IntSet')


def corrected_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('unreviewed-teavm-coroutine-source')
    source = raw.decode('utf-8')
    if source.count(BEFORE) != 1 or source.count(DOMAIN) != 1:
        raise ValueError('unreviewed-teavm-coroutine-predicate')
    source = source.replace(DOMAIN, COPIED_DOMAIN).replace(BEFORE, AFTER)
    # Splitting block zero appends its continuation at the old block count.
    # Liveness still describes the original graph, including that block zero.
    for before, after in LIVENESS_REPLACEMENTS:
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-coroutine-liveness')
        source = source.replace(before, after)
    for before, after in COPY_COST_REPLACEMENTS:
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-coroutine-copy-cost')
        source = source.replace(before, after)
    for before, after in COPY_OBSERVER_REPLACEMENTS:
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-copy-observer')
        source = source.replace(before, after)
    # The published 0.15.0 artifacts relocate HPPC, unlike the Git source tree.
    for name in RELOCATED_IMPORTS:
        before = 'import com.carrotsearch.hppc.' + name + ';'
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-coroutine-relocation')
        source = source.replace(before, 'import org.teavm.hppc.' + name + ';')
    return source.encode('utf-8')


def corrected_type_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != TYPE_INFERER_SHA256:
        raise ValueError('unreviewed-teavm-type-source')
    source = raw.decode('utf-8')
    if source.count(TYPE_SEED_BEFORE) != 1 or source.count(TYPE_ELEMENT_BEFORE) != 1:
        raise ValueError('unreviewed-teavm-type-seed')
    return source.replace(TYPE_SEED_BEFORE, TYPE_SEED_AFTER).replace(
        TYPE_ELEMENT_BEFORE, TYPE_ELEMENT_AFTER).encode('utf-8')


def corrected_async_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != ASYNC_SOURCE_SHA256:
        raise ValueError('unreviewed-teavm-async-finder-source')
    source = raw.decode('utf-8')
    if source.count(ASYNC_BEFORE) != 1:
        raise ValueError('unreviewed-teavm-async-finder-preimage')
    if source.count(CHECKPOINT_FIND_BEFORE) != 1:
        raise ValueError('unreviewed-teavm-checkpoint-find-preimage')
    return source.replace(ASYNC_BEFORE, CHECKPOINT_VALIDATION + ASYNC_AFTER).replace(
        CHECKPOINT_FIND_BEFORE, CHECKPOINT_FIND_AFTER).encode('utf-8')


def checked_jars(compiler, project: Path) -> list[Path]:
    from tools.java_guest.compiler import source_module
    module = source_module(compiler.sdk / 'tools/dependencies.py')
    observed = module.cache_inventory(compiler.dependency_cache)
    lock = json.loads(read_file(project / 'dependencies.lock.json'))
    module.verify_inventory(observed, lock, project / 'gradle/verification-metadata.xml')
    selected = []
    for row in observed['artifacts']:
        parts = row['path'].split('/')
        group, name, version, filename = '.'.join(parts[:-3]), *parts[-3:]
        candidates = list((compiler.dependency_cache / group / name / version).glob('*/' + filename))
        if len(candidates) != 1:
            raise ValueError('coroutine-patch-jar-selection')
        path = candidates[0]
        if module.file_identity(path) != {'sha256': row['sha256'], 'size': row['size']}:
            raise ValueError('coroutine-patch-jar-mutated')
        selected.append(path)
    return selected


def jar_identities(cache: Path, jars: list[Path]) -> list[dict]:
    result = []
    for path in jars:
        group, name, version, _key, filename = path.relative_to(cache).parts
        raw = read_file(path, MAX_JAR_BYTES)
        result.append({'coordinate': '/'.join((group.replace('.', '/'), name, version, filename)),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    return sorted(result, key=lambda row: row['coordinate'])


def check_relocated_classes(jars: list[Path]) -> None:
    import io
    selected = [path for path in jars if path.name == 'teavm-relocated-libs-hppc-0.15.0.jar']
    if len(selected) != 1:
        raise ValueError('coroutine-patch-relocated-library')
    with zipfile.ZipFile(io.BytesIO(read_file(selected[0], MAX_JAR_BYTES))) as jar:
        entries = jar.infolist()
        if len(entries) > 32768 or len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('coroutine-patch-relocated-entries')
        for name in RELOCATED_IMPORTS:
            entry = jar.getinfo('org/teavm/hppc/' + name + '.class')
            if entry.is_dir() or entry.file_size > 1024 * 1024 or not jar.read(entry).startswith(b'\xca\xfe\xba\xbe'):
                raise ValueError('coroutine-patch-relocated-class')


def jar_entries(path: Path) -> dict[str, bytes]:
    raw = read_file(path, MAX_JAR_BYTES)
    import io
    result, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as jar:
        for member in jar.infolist():
            if (len(result) >= 32768 or member.filename in result
                    or member.file_size > 16 * 1024 * 1024 or member.flag_bits & 1
                    or member.filename.startswith('/') or '\\' in member.filename
                    or '..' in member.filename.split('/')):
                raise ValueError('coroutine-patch-jar-entry')
            total += member.file_size
            if total > 128 * 1024 * 1024:
                raise ValueError('coroutine-patch-jar-bound')
            result[member.filename] = jar.read(member)
    if ({name for name in result if name.startswith(CLASS_ROOT + 'CoroutineTransformation')
            and name.endswith('.class')} != COROUTINE_CLASSES
            or {name for name in result if name.startswith(TYPE_ROOT + 'TypeInferer')
                and name.endswith('.class')} != TYPE_CLASSES
            or {name for name in result if name.startswith(TYPE_ROOT + 'AsyncMethodFinder')
                and name.endswith('.class')} != ASYNC_CLASSES):
        raise ValueError('coroutine-patch-class-closure')
    return result


def replace_jar(original: Path, classes: Path, target: Path) -> dict:
    entries = jar_entries(original)
    actual = {path.relative_to(classes).as_posix() for path in classes.rglob('*') if path.is_file()}
    if actual != PATCH_CLASSES | CONTROLS or target.exists():
        raise ValueError('coroutine-patch-compiled-closure')
    identities = {}
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for name, raw in sorted(entries.items()):
            if name in PATCH_CLASSES:
                replacement = read_file(classes / name, 1024 * 1024)
                if not replacement.startswith(b'\xca\xfe\xba\xbe'):
                    raise ValueError('coroutine-patch-class-format')
                identities[name] = {'originalSha256': hashlib.sha256(raw).hexdigest(),
                    'replacementSha256': hashlib.sha256(replacement).hexdigest()}
                raw = replacement
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            output.writestr(entry, raw)
    observed = jar_entries(target)
    if set(observed) != set(entries) or any(observed[name] != raw
            for name, raw in entries.items() if name not in PATCH_CLASSES):
        raise ValueError('coroutine-patch-unrelated-jar-entry-changed')
    return {'originalJarSha256': hashlib.sha256(read_file(original, MAX_JAR_BYTES)).hexdigest(),
        'replacementJarSha256': hashlib.sha256(read_file(target, MAX_JAR_BYTES)).hexdigest(),
        'replacedClasses': identities, 'unchangedEntries': len(entries) - len(PATCH_CLASSES)}


CLASSPATH_DECLARATION = "dependencies { classpath 'org.teavm:teavm-gradle-plugin:0.15.0' }"
_CLASSPATH_RECORD_HOOK = """
// Record the original resolved compiler graph in the already-required classes task.
tasks.named('classes') {
    doLast {
        def configuration = buildscript.configurations.classpath
        def artifacts = configuration.resolvedConfiguration.resolvedArtifacts
        def rows = configuration.files.collect { selected ->
            def artifact = artifacts.find { it.file.canonicalFile == selected.canonicalFile }
            if (artifact == null || !selected.isFile() || selected.length() > 67108864) {
                throw new GradleException('coroutine-patch-original-classpath-artifact')
            }
            def id = artifact.moduleVersion.id
            [coordinate: id.group.replace('.', '/') + '/' + id.name + '/' + id.version + '/' + selected.name,
             sha256: java.security.MessageDigest.getInstance('SHA-256').digest(selected.bytes).encodeHex().toString(),
             bytes: selected.length()]
        }
        if (rows.isEmpty() || rows.size() > 512) throw new GradleException('coroutine-patch-original-classpath-bound')
        def text = groovy.json.JsonOutput.toJson([
            schemaVersion: 'latent.java.original-compiler-classpath.v1',
            outOfProcess: tasks.named('generateC').get().outOfProcess.get(), files: rows])
        if (text.getBytes('UTF-8').length > 262144) throw new GradleException('coroutine-patch-original-classpath-bound')
        file('coroutine-patch-original-classpath.json').text = text
    }
}
"""


def record_original_classpath(project: Path) -> None:
    build = project / 'build.gradle'
    script = read_file(build).decode('utf-8')
    if script.count(CLASSPATH_DECLARATION) != 1 or _CLASSPATH_RECORD_HOOK in script:
        raise ValueError('coroutine-patch-classpath-record-drift')
    build.write_bytes((script + _CLASSPATH_RECORD_HOOK).encode('utf-8'))


def original_classpath(compiler, project: Path, jars: list[Path]) -> list[Path]:
    from tools.rust_capsule_project import decode_json
    record = decode_json(read_file(project / 'coroutine-patch-original-classpath.json', 262144))
    if (type(record) is not dict or set(record) != {'schemaVersion', 'outOfProcess', 'files'}
            or record['schemaVersion'] != 'latent.java.original-compiler-classpath.v1'
            or record['outOfProcess'] is not False or type(record['files']) is not list
            or not 0 < len(record['files']) <= 512):
        raise ValueError('coroutine-patch-original-classpath-schema')
    identities = {row['coordinate']: row for row in jar_identities(compiler.dependency_cache, jars)}
    paths = {jar_identities(compiler.dependency_cache, [path])[0]['coordinate']: path for path in jars}
    selected, seen = [], set()
    for row in record['files']:
        if (type(row) is not dict or set(row) != {'coordinate', 'sha256', 'bytes'}
                or type(row['coordinate']) is not str or row['coordinate'] in seen
                or type(row['bytes']) is not int or row != identities.get(row['coordinate'])):
            raise ValueError('coroutine-patch-original-classpath-identity')
        seen.add(row['coordinate']); selected.append(paths[row['coordinate']])
    if sum(path.name == 'teavm-core-0.15.0.jar' for path in selected) != 1:
        raise ValueError('coroutine-patch-original-classpath-core')
    return selected


def _groovy_path(path: Path) -> str:
    value = path.as_posix()
    if any(char in value for char in '\x00\r\n'):
        raise ValueError('coroutine-patch-classpath-path')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def stage(compiler, project: Path, destination: Path) -> dict:
    observe_copy_cost = getattr(compiler, '_observe_public_copy_cost', False)
    if type(observe_copy_cost) is not bool:
        raise ValueError('coroutine-copy-observer-selection')
    if observe_copy_cost:
        from tools.java_guest.public_wineh import public_sources
        public_sources(compiler.directory.parent)
    # The first ordinary classes task has already populated the strictly checked cache.
    jars = checked_jars(compiler, project)
    check_relocated_classes(jars)
    captured_classpath = original_classpath(compiler, project, jars)
    original = [path for path in jars if path.name == 'teavm-core-0.15.0.jar']
    if len(original) != 1:
        raise ValueError('coroutine-patch-core-selection')
    identities = jar_identities(compiler.dependency_cache, jars)
    sdk = compiler.sdk / 'fibers/compiler-patch'
    folder = project / 'compiler-patch'; folder.mkdir()
    source = folder / 'CoroutineTransformation.java'
    raw = read_file(sdk / 'CoroutineTransformation.java')
    corrected = corrected_source(raw); source.write_bytes(corrected)
    control = folder / 'Check.java'; control.write_bytes(read_file(sdk / 'Check.java'))
    type_raw = read_file(sdk / 'TypeInferer.java')
    type_source = folder / 'TypeInferer.java'
    corrected_types = corrected_type_source(type_raw); type_source.write_bytes(corrected_types)
    array_control = folder / 'ArrayTypeCheck.java'
    array_control.write_bytes(read_file(sdk / 'ArrayTypeCheck.java'))
    async_raw = read_file(sdk / 'AsyncMethodFinder.java')
    async_source = folder / 'AsyncMethodFinder.java'
    corrected_async = corrected_async_source(async_raw); async_source.write_bytes(corrected_async)
    monitor_control = folder / 'MonitorAsyncControl.java'
    monitor_control.write_bytes(read_file(sdk / 'MonitorAsyncControl.java'))
    # Compiler.run provides the original process, output and remaining-time bounds.
    classes = folder / 'classes'
    read_file(sdk / 'Compile.java')
    compiler.run('java-coroutine-patch', 'java', sdk / 'Compile.java', source, control, classes,
                 os.pathsep.join(map(str, jars)), type_source, array_control, async_source, monitor_control)
    replacement = folder / 'teavm-core-patched.jar'
    receipt = replace_jar(original[0], classes, replacement)
    for mode, selected in (('original', original[0]), ('corrected', replacement)):
        classpath = os.pathsep.join(map(str, [selected, classes, *[p for p in jars if p != original[0]]]))
        observed = compiler.run('java-coroutine-' + mode + '-control', 'java', '-cp', classpath,
            'org.teavm.backend.lowlevel.transform.Check', mode)
        if json.loads(observed) != {'schemaVersion': 'latent.java.coroutine-phi-control.v1',
                'mode': mode, 'passed': True}:
            raise ValueError('coroutine-patch-real-ir-control')
        monitor = compiler.run('java-coroutine-monitor-' + mode + '-control', 'java', '-cp', classpath,
            'org.teavm.dependency.MonitorAsyncControl', mode)
        if json.loads(monitor) != {'schemaVersion': 'latent.java.monitor-async-control.v1',
                'mode': mode, 'passed': True}:
            raise ValueError('coroutine-patch-real-monitor-async-control')
    cost_classpath = os.pathsep.join(map(str, [replacement, classes,
        *[p for p in jars if p != original[0]]]))
    cost_controls = ['domain-choice', 'reducible-parity', 'overflow-before-copy']
    cost = compiler.run('java-coroutine-copy-cost-control', 'java', '-cp', cost_classpath,
        'org.teavm.backend.lowlevel.transform.Check', 'copy-cost')
    if json.loads(cost) != {'schemaVersion': 'latent.java.coroutine-copy-cost-control.v1',
            'cases': cost_controls, 'passed': True}:
        raise ValueError('coroutine-patch-real-copy-cost-control')
    if identities != jar_identities(compiler.dependency_cache, checked_jars(compiler, project)):
        raise ValueError('coroutine-patch-original-input-mutated')
    build = project / 'build.gradle'; script = read_file(build).decode('utf-8')
    # Replace, rather than compete with, the exact original resolved graph.
    # Its transitive files remain in their original order; no application JARs
    # or guessed dependencies are added to the compiler loader.
    selected_classpath = [replacement if path == original[0] else path for path in captured_classpath]
    after = "dependencies { classpath files(" + ', '.join(map(_groovy_path, selected_classpath)) + ") }"
    if script.count(CLASSPATH_DECLARATION) != 1 or script.count(_CLASSPATH_RECORD_HOOK) != 1:
        raise ValueError('coroutine-patch-buildscript-drift')
    script = script.replace(_CLASSPATH_RECORD_HOOK, '').replace(CLASSPATH_DECLARATION, after)
    script += '''
tasks.named('generateC') {
    doFirst {
        if (outOfProcess.get() != false) throw new GradleException('coroutine-patch-process-mode-drift')
        def actual = Class.forName('org.teavm.backend.lowlevel.transform.CoroutineTransformation',
            false, org.teavm.backend.c.CTarget.class.classLoader)
        def selected = file('compiler-patch/teavm-core-patched.jar').canonicalFile
        def source = new File(actual.protectionDomain.codeSource.location.toURI())
        if (!java.nio.file.Files.isRegularFile(source.toPath(), java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            throw new GradleException('coroutine-patch-loaded-source-bound')
        }
        def observed = source.canonicalFile
        if (observed.length() > 67108864) throw new GradleException('coroutine-patch-loaded-source-bound')
        def hash = java.security.MessageDigest.getInstance('SHA-256').digest(selected.bytes).encodeHex().toString()
        if (hash != '__PATCH_SHA256__') throw new GradleException('coroutine-patch-loaded-jar-mutated')
        def actualHash = java.security.MessageDigest.getInstance('SHA-256').digest(observed.bytes).encodeHex().toString()
        def kind = observed == selected ? 'owned-replacement' : actualHash == hash ? 'byte-identical-copy' : 'other'
        println('latent.java.coroutine-loader.v1 ' + groovy.json.JsonOutput.toJson([
            sourceKind: kind, sourceSha256: actualHash, expectedSha256: hash]))
        // Gradle 9.1 agent transforms may expose a byte-identical original copy.
        // Identity, rather than its cache pathname, is the compiler boundary.
        if (actualHash != hash) {
            throw new GradleException('coroutine-patch-loaded-class-mismatch')
        }
        def expectedClasses = new groovy.json.JsonSlurper().parseText('__EXPECTED_CLASSES__')
        def loadedClasses = [:]
        expectedClasses.each { name, expected ->
            def loadedClass = Class.forName(name.substring(0, name.length() - 6).replace('/', '.'), false, actual.classLoader)
            if (loadedClass.classLoader != actual.classLoader ||
                    new File(loadedClass.protectionDomain.codeSource.location.toURI()).canonicalFile != observed) {
                throw new GradleException('coroutine-patch-loaded-class-source')
            }
            def resource = actual.classLoader.getResource(name)
            def connection = resource?.openConnection()
            if (!(connection instanceof java.net.JarURLConnection) ||
                    new File(connection.jarFileURL.toURI()).canonicalFile != observed) {
                throw new GradleException('coroutine-patch-loaded-class-resource')
            }
            connection.useCaches = false
            def bytes = connection.inputStream.withCloseable { it.readNBytes(1048577) }
            if (bytes.length > 1048576) throw new GradleException('coroutine-patch-loaded-class-bound')
            def classHash = java.security.MessageDigest.getInstance('SHA-256').digest(bytes).encodeHex().toString()
            if (classHash != expected) throw new GradleException('coroutine-patch-loaded-class-bytes')
            loadedClasses[name] = classHash
        }
        __COPY_COST_OBSERVER__
        file('compiler-patch/loaded.json').text = groovy.json.JsonOutput.toJson([
            schemaVersion: 'latent.java.coroutine-compiler-load.v1',
            selectedOwnedReplacement: true, replacementJarSha256: hash,
            loadedJarSha256: actualHash, codeSourceKind: kind, loadedClasses: loadedClasses])
    }
}
'''.replace('__PATCH_SHA256__', receipt['replacementJarSha256']).replace('__EXPECTED_CLASSES__',
        json.dumps({name: row['replacementSha256'] for name, row in receipt['replacedClasses'].items()},
                   sort_keys=True, separators=(',', ':')))
    observer_hook = ("if (System.getProperty('" + COPY_OBSERVER_PROPERTY + "') != null) "
        "throw new GradleException('coroutine-copy-observer-ambient-selection');")
    if observe_copy_cost:
        observer_hook += ("\n        System.setProperty('" + COPY_OBSERVER_PROPERTY + "', '"
                          + COPY_OBSERVER_TOKEN + "');")
    script = script.replace('__COPY_COST_OBSERVER__', observer_hook)
    build.write_bytes(script.encode('utf-8'))
    receipt.update(schemaVersion='latent.java.coroutine-compiler-patch.v1',
        upstreamSourceSha256=UPSTREAM_SHA256, correctedSourceSha256=hashlib.sha256(corrected).hexdigest(),
        realOriginalIrDefectObserved=True, realCorrectedIrInputsPreserved=True,
        realOriginalEntryLivenessDefectObserved=True, realCorrectedEntryLiveValuePreserved=True,
        upstreamTypeSourceSha256=TYPE_INFERER_SHA256,
        correctedTypeSourceSha256=hashlib.sha256(corrected_types).hexdigest(),
        realOriginalPrimitiveArrayRootDefectObserved=True,
        realCorrectedArrayTypesAndReferenceRootsPreserved=True,
        realCorrectedRestoredArrayPrimitiveTypePreserved=True,
        structuralCopyCostPolicy='initial-ir-structural-copy-v1',
        publicCopyCostObserverSelected=observe_copy_cost,
        publicCopyCostObserverMaximumRecordBytes=131072,
        realStructuralCopyCostControls=cost_controls,
        upstreamAsyncFinderSourceSha256=ASYNC_SOURCE_SHA256,
        correctedAsyncFinderSourceSha256=hashlib.sha256(corrected_async).hexdigest(),
        realOriginalMonitorBoundaryDefectObserved=True,
        realCorrectedMonitorOnlyAndMixedBoundariesPreserved=True,
        realCorrectedMonitorCallerAndFamilyClosurePreserved=True,
        realNoThreadStartAndUnrelatedMethodNegativesPreserved=True,
        originalInputsUnchanged=True, checkedCompilerJars=identities,
        publishedHppcRelocation='org.teavm.hppc',
        originalBuildscriptClasspath=[jar_identities(compiler.dependency_cache, [path])[0]
            for path in captured_classpath])
    preparation = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(preparation) > 262144:
        raise ValueError('coroutine-patch-preparation-bound')
    (compiler.directory / 'coroutine-compiler-preparation.json').write_bytes(preparation)
    return receipt


def loaded(project: Path, receipt: dict, *, compiler=None) -> dict:
    if compiler is not None and receipt['checkedCompilerJars'] != jar_identities(
            compiler.dependency_cache, checked_jars(compiler, project)):
        raise ValueError('coroutine-patch-original-input-mutated')
    actual = json.loads(read_file(project / 'compiler-patch/loaded.json', 4096))
    if (type(actual) is not dict or actual.get('selectedOwnedReplacement') is not True
            or type(actual.get('codeSourceKind')) is not str
            or actual.get('codeSourceKind') not in {'owned-replacement', 'byte-identical-copy'}
            or actual != {'schemaVersion': 'latent.java.coroutine-compiler-load.v1',
            'selectedOwnedReplacement': True, 'replacementJarSha256': receipt['replacementJarSha256'],
            'loadedJarSha256': receipt['replacementJarSha256'], 'codeSourceKind': actual.get('codeSourceKind'),
            'loadedClasses': {name: row['replacementSha256'] for name, row in receipt['replacedClasses'].items()}}):
        raise ValueError('coroutine-patch-loaded-receipt-mismatch')
    if hashlib.sha256(read_file(project / 'compiler-patch/teavm-core-patched.jar', MAX_JAR_BYTES)).hexdigest() != receipt['replacementJarSha256']:
        raise ValueError('coroutine-patch-used-jar-mutated')
    return {**receipt, 'loadedCompiler': actual}

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
        validateNonsuspendableProgress();
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

    // This is a deliberately narrow, name-independent ranking proof. It never
    // infers progress from a volatile read, a library/package name or fuel.
    private boolean finiteCountedLoops(ProgramReader reader) {
        org.teavm.model.Program program = boundedProgressProgram(reader);
        if (program == null) {
            return false;
        }
        org.teavm.common.Graph graph = ProgramUtils.buildControlFlowGraph(program);
        int edges = 0;
        for (int index = 0; index < graph.size(); ++index) {
            int count = graph.outgoingEdgesCount(index);
            if (count > 262144 - edges) {
                throw checkpointRefusal("java-checkpoint-analysis-bound-741");
            }
            edges += count;
        }
        if (org.teavm.common.GraphUtils.isIrreducible(graph)) {
            return false;
        }
        org.teavm.common.LoopGraph loops = new org.teavm.common.LoopGraph(graph);
        org.teavm.common.DominatorTree dominators = org.teavm.common.GraphUtils.buildDominatorTree(graph);
        org.teavm.model.Instruction[] definitions = new org.teavm.model.Instruction[program.variableCount()];
        int[] places = new int[program.variableCount()];
        java.util.Arrays.fill(places, -1);
        org.teavm.model.util.DefinitionExtractor extractor = new org.teavm.model.util.DefinitionExtractor();
        for (org.teavm.model.BasicBlock block : program.getBasicBlocks()) {
            if (block.getExceptionVariable() != null) {
                int index = block.getExceptionVariable().getIndex();
                if (places[index] != -1) {
                    return false;
                }
                places[index] = block.getIndex();
            }
            for (org.teavm.model.Phi phi : block.getPhis()) {
                int index = phi.getReceiver().getIndex();
                if (places[index] != -1) {
                    return false;
                }
                places[index] = block.getIndex();
            }
            for (org.teavm.model.Instruction instruction : block) {
                if (instruction instanceof org.teavm.model.instructions.MonitorEnterInstruction) {
                    return false; // A finite body does not bound a contended lock acquisition.
                }
                if (instruction instanceof org.teavm.model.instructions.InvokeInstruction
                        && ((org.teavm.model.instructions.InvokeInstruction) instruction).getMethod()
                                .getName().equals("<clinit>")) {
                    return false; // A direct call is not the owned initializeClass protocol.
                }
                instruction.acceptVisitor(extractor);
                for (org.teavm.model.Variable variable : extractor.getDefinedVariables()) {
                    int index = variable.getIndex();
                    if (places[index] != -1) {
                        return false; // A non-SSA value cannot establish this proof.
                    }
                    places[index] = block.getIndex();
                    definitions[index] = instruction;
                }
            }
        }
        org.teavm.common.Loop[] rankedLoops = new org.teavm.common.Loop[graph.size()];
        for (org.teavm.common.Loop loop : loops.knownLoops()) {
            if (!finiteCountedLoop(program, graph, loops, dominators, loop, definitions, places)) {
                return false;
            }
            rankedLoops[loop.getHead()] = loop;
        }
        // Pinned LoopGraph does not enumerate every CFG cycle: in particular,
        // a self-edge is inspected after its own DFS frame is marked done.
        // Remove only backedges covered by a proved rank, then independently
        // require the remaining normal and exceptional graph to be acyclic.
        return finiteResidualProgressGraph(graph, loops, dominators, rankedLoops);
    }

    private boolean rankedProgressBackedge(org.teavm.common.LoopGraph loops,
            org.teavm.common.DominatorTree dominators, org.teavm.common.Loop[] rankedLoops,
            int source, int target) {
        org.teavm.common.Loop loop = rankedLoops[target];
        return loop != null && insideProgressLoop(loops, loop, source)
                && dominators.dominates(target, source);
    }

    private boolean finiteResidualProgressGraph(org.teavm.common.Graph graph,
            org.teavm.common.LoopGraph loops, org.teavm.common.DominatorTree dominators,
            org.teavm.common.Loop[] rankedLoops) {
        // Both passes visit only the already bounded CFG. Each block enters
        // this fixed-size queue once, when its residual in-degree becomes zero.
        int[] incoming = new int[graph.size()];
        for (int source = 0; source < graph.size(); ++source) {
            for (int target : graph.outgoingEdges(source)) {
                if (!rankedProgressBackedge(loops, dominators, rankedLoops, source, target)) {
                    ++incoming[target];
                }
            }
        }
        int[] queue = new int[graph.size()];
        int end = 0;
        for (int index = 0; index < graph.size(); ++index) {
            if (incoming[index] == 0) {
                queue[end++] = index;
            }
        }
        for (int next = 0; next < end; ++next) {
            int source = queue[next];
            for (int target : graph.outgoingEdges(source)) {
                if (!rankedProgressBackedge(loops, dominators, rankedLoops, source, target)
                        && --incoming[target] == 0) {
                    queue[end++] = target;
                }
            }
        }
        return end == graph.size();
    }

    private org.teavm.model.Program boundedProgressProgram(ProgramReader reader) {
        if (reader == null || reader.basicBlockCount() <= 0 || reader.basicBlockCount() > 65536
                || reader.variableCount() <= 0 || reader.variableCount() > 262144) {
            return null;
        }
        int work = 0;
        for (int index = 0; index < reader.basicBlockCount(); ++index) {
            org.teavm.model.BasicBlockReader block = reader.basicBlockAt(index);
            if (block == null) {
                return null;
            }
            // ProgramUtils' CFG includes exceptional edges. Count handlers now;
            // the same ranking must cover a backedge through a catch block.
            work = Math.addExact(work, block.readTryCatchBlocks().size());
            if (work > 262144) {
                return null;
            }
            for (org.teavm.model.PhiReader phi : block.readPhis()) {
                work = Math.addExact(work, 1);
                work = Math.addExact(work, phi.readIncomings().size());
                if (work > 262144) {
                    return null;
                }
            }
            org.teavm.model.InstructionIterator iterator = block.iterateInstructions();
            while (iterator.hasNext()) {
                iterator.next();
                if (++work > 262144) {
                    return null;
                }
            }
        }
        org.teavm.model.Program program = ProgramUtils.copy(reader);
        for (org.teavm.model.BasicBlock block : program.getBasicBlocks()) {
            for (org.teavm.model.Instruction instruction : block) {
                if (instruction instanceof org.teavm.model.instructions.SwitchInstruction) {
                    work = Math.addExact(work,
                            ((org.teavm.model.instructions.SwitchInstruction) instruction).getEntries().size());
                    if (work > 262144) {
                        return null;
                    }
                }
            }
        }
        return program;
    }

    private boolean insideProgressLoop(org.teavm.common.LoopGraph loops,
            org.teavm.common.Loop loop, int block) {
        if (block < 0) {
            return false;
        }
        org.teavm.common.Loop actual = loops.loopAt(block);
        return actual != null && actual.isChildOf(loop);
    }

    private boolean finiteCountedLoop(org.teavm.model.Program program, org.teavm.common.Graph graph,
            org.teavm.common.LoopGraph loops, org.teavm.common.DominatorTree dominators,
            org.teavm.common.Loop loop,
            org.teavm.model.Instruction[] definitions, int[] places) {
        org.teavm.model.BasicBlock head = program.basicBlockAt(loop.getHead());
        if (!(head.getLastInstruction() instanceof org.teavm.model.instructions.BranchingInstruction)) {
            return false;
        }
        org.teavm.model.instructions.BranchingInstruction branch =
                (org.teavm.model.instructions.BranchingInstruction) head.getLastInstruction();
        boolean consequentInside = insideProgressLoop(loops, loop, branch.getConsequent().getIndex());
        boolean alternativeInside = insideProgressLoop(loops, loop, branch.getAlternative().getIndex());
        if (consequentInside == alternativeInside) {
            return false;
        }
        int continuation = consequentInside ? branch.getConsequent().getIndex() : branch.getAlternative().getIndex();
        for (org.teavm.model.TryCatchBlock handler : head.getTryCatchBlocks()) {
            if (insideProgressLoop(loops, loop, handler.getHandler().getIndex())) {
                return false; // A failing bound computation must not bypass the strict test.
            }
        }
        org.teavm.model.instructions.BranchingCondition condition = branch.getCondition();
        if (!(consequentInside && condition == org.teavm.model.instructions.BranchingCondition.LESS
                || alternativeInside
                && condition == org.teavm.model.instructions.BranchingCondition.GREATER_OR_EQUAL)) {
            return false;
        }
        // Pinned ProgramParser translates IF_ICMP{LT,GE} to signed INT
        // COMPARE_GREATER followed by a unary branch, not a subtraction.
        org.teavm.model.Instruction comparison = definitions[branch.getOperand().getIndex()];
        if (!(comparison instanceof org.teavm.model.instructions.BinaryInstruction)) {
            return false;
        }
        org.teavm.model.instructions.BinaryInstruction compare =
                (org.teavm.model.instructions.BinaryInstruction) comparison;
        if (compare.getOperation() != org.teavm.model.instructions.BinaryOperation.COMPARE_GREATER
                || compare.getOperandType() != org.teavm.model.instructions.NumericOperandType.INT
                || compare.getBasicBlock() != head) {
            return false;
        }
        int induction = compare.getFirstOperand().getIndex();
        for (org.teavm.model.Phi phi : head.getPhis()) {
            if (phi.getReceiver().getIndex() != induction) {
                continue;
            }
            int outside = 0, inside = 0;
            java.util.Set<Integer> incoming = new java.util.HashSet<>();
            for (org.teavm.model.Incoming edge : phi.getIncomings()) {
                if (!incoming.add(edge.getSource().getIndex())) {
                    return false;
                }
                org.teavm.model.Instruction value = definitions[edge.getValue().getIndex()];
                if (!insideProgressLoop(loops, loop, edge.getSource().getIndex())) {
                    if (insideProgressLoop(loops, loop, places[edge.getValue().getIndex()])) {
                        return false;
                    }
                    ++outside;
                } else {
                    if (edge.getSource() != head && !dominators.dominates(continuation,
                            edge.getSource().getIndex())) {
                        return false;
                    }
                    if (!(value instanceof org.teavm.model.instructions.BinaryInstruction)) {
                        return false;
                    }
                    org.teavm.model.instructions.BinaryInstruction update =
                            (org.teavm.model.instructions.BinaryInstruction) value;
                    if (update.getOperation() != org.teavm.model.instructions.BinaryOperation.ADD
                            || update.getOperandType() != org.teavm.model.instructions.NumericOperandType.INT
                            || update.getFirstOperand().getIndex() != induction
                            || !insideProgressLoop(loops, loop, places[edge.getValue().getIndex()])) {
                        return false;
                    }
                    org.teavm.model.Instruction step = definitions[update.getSecondOperand().getIndex()];
                    if (!(step instanceof org.teavm.model.instructions.IntegerConstantInstruction)
                            || ((org.teavm.model.instructions.IntegerConstantInstruction) step).getConstant() != 1) {
                        return false;
                    }
                    ++inside;
                }
            }
            int[] predecessors = graph.incomingEdges(head.getIndex());
            if (outside == 0 || inside == 0 || incoming.size() != predecessors.length) {
                return false;
            }
            for (int predecessor : predecessors) {
                if (!incoming.contains(predecessor)) {
                    return false;
                }
            }
            // The head dominates a reducible natural loop. Every backedge now
            // carries i+1. The long rank Integer.MAX_VALUE-i decreases on every
            // cycle, even for a changing signed limit. Its strict test requires
            // i<limit<=Integer.MAX_VALUE, so a traversed backedge cannot wrap.
            return true;
        }
        return false;
    }

    private void validateNonsuspendableProgress() {
        progressRuntimeProofs.clear(); // Never reuse a proof across completion rounds.
        progressOriginalClasses.clear();
        progressMetadataProofs.clear();
        progressPlatformProofs.clear();
        // Unlike checkpoint-call validation, this closure is required even if
        // Activation.checkpoint is entirely unreachable in the final programme.
        java.util.Map<MethodReference, Integer> contexts = new java.util.HashMap<>();
        java.util.List<MethodReference> pending = new java.util.ArrayList<>();
        int work = 0;
        for (MethodReference reference : dependency.getReachableMethods()) {
            if (++work > 65536 || reference == null) {
                throw checkpointRefusal("java-checkpoint-analysis-bound-741");
            }
            org.teavm.dependency.MethodDependencyInfo linked = dependency.getMethod(reference);
            // Reachable methods also includes speculative links that have never
            // been called or used. They are not executable progress roots.
            if (linked != null && !linked.isUsed() && !linked.isCalled()) {
                continue;
            }
            ClassReader cls = classSource.get(reference.getClassName());
            MethodReader method = cls == null ? null : cls.getMethod(reference.getDescriptor());
            if (method == null) {
                // CTarget speculatively links Allocator.<clinit> even when the
                // exact pinned class declares no initializer. Authenticate the
                // absence and complete layout; never waive a real initializer.
                if (pinnedAbsentRuntimeInitializer(cls, reference)) {
                    continue;
                }
                // linkMethod records missing declarations in reachedMethods
                // before it checks isMissing(). An ordinary absent method on
                // a known managed class has no body/annotation to classify;
                // its normal missing-method diagnostic remains the compiler's.
                // Never defer an unknown class or an excluded root. Missing
                // callees reached from an excluded context still refuse below.
                if (cls == null || reference.getName().equals("<clinit>")
                        || progressRuntimeClassIdentity(cls.getName()) != null
                        || cls.getAnnotations().get("org.teavm.interop.Unmanaged") != null) {
                    throw checkpointRefusal("java-checkpoint-unresolved-741");
                }
                continue;
            }
            if (progressRuntimeClassIdentity(cls.getName()) != null
                    || reference.getName().equals("<clinit>")
                    || method.getAnnotations().get("org.teavm.interop.Unmanaged") != null
                    || cls.getAnnotations().get("org.teavm.interop.Unmanaged") != null) {
                contexts.put(reference, pending.size());
                pending.add(reference);
            }
        }
        MethodReference managedEntry = new MethodReference(Fiber.class, "start", void.class);
        java.util.List<int[]> edges = new java.util.ArrayList<>();
        work = 0;
        for (int index = 0; index < pending.size(); ++index) {
            MethodReference reference = pending.get(index);
            ClassReader cls = classSource.get(reference.getClassName());
            MethodReader method = cls == null ? null : cls.getMethod(reference.getDescriptor());
            CallGraphNode node = callGraph.getNode(reference);
            if (method == null || node == null) {
                throw checkpointRefusal("java-checkpoint-unresolved-741");
            }
            if (reference.equals(managedEntry) && method.getLevel() == org.teavm.model.AccessLevel.PRIVATE
                    && !method.hasModifier(ElementModifier.STATIC)) {
                if (method.getAnnotations().get("org.teavm.interop.Unmanaged") != null
                        || cls.getAnnotations().get("org.teavm.interop.Unmanaged") != null
                        || method.getAnnotations().get("org.teavm.interop.Async") != null) {
                    throw checkpointRefusal("java-checkpoint-nonsuspendable-context-741");
                }
                if (!pinnedFiberEntry(method)) {
                    throw checkpointRefusal("java-checkpoint-unresolved-741");
                }
                continue; // The existing, proven new managed execution context.
            }
            // The runtime proof must be closed before this pass is enabled:
            // source-bound heap/metadata families are not a package exemption.
            boolean runtime = progressRuntimeClassIdentity(cls.getName()) != null;
            if (runtime) {
                if (!finiteRuntimeMethod(cls, method)) {
                    throw checkpointRefusal("java-checkpoint-nonsuspendable-progress-741");
                }
                // The pinned runtime certificate bounds its own loops and
                // internal ABI helpers. Ordinary Java callees still need the
                // same transitive progress proof as application code.
                try {
                    if (closedRuntimeCalls(method.getProgram())) {
                        continue;
                    }
                } catch (Exception unavailable) {
                    throw checkpointRefusal("java-checkpoint-unresolved-741");
                }
            }
            if (!runtime && method.getProgram() == null && progressNativePrimitive(method)) {
                continue;
            }
            if (!runtime && (method.hasModifier(ElementModifier.SYNCHRONIZED)
                    || method.getAnnotations().get("org.teavm.interop.Async") != null)) {
                throw checkpointRefusal("java-checkpoint-nonsuspendable-context-741");
            }
            MethodReference delegate = !runtime && method.getProgram() == null
                    ? progressNativeDelegate(cls, method) : null;
            if (!runtime && (method.getProgram() == null ? delegate == null
                    : !finiteCountedLoops(method.getProgram()))) {
                throw checkpointRefusal("java-checkpoint-nonsuspendable-progress-741");
            }
            if (delegate != null) {
                Integer targetIndex = contexts.get(delegate);
                if (targetIndex == null) {
                    if (pending.size() == 65536) {
                        throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                    }
                    targetIndex = pending.size();
                    contexts.put(delegate, targetIndex);
                    pending.add(delegate);
                }
                if (++work > 262144) {
                    throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                }
                edges.add(new int[] { index, targetIndex });
            }
            for (CallSite site : node.getCallSites()) {
                if (++work > 262144 || site == null) {
                    throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                }
                for (CallGraphNode callee : site.getCalledMethods()) {
                    if (++work > 262144) {
                        throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                    }
                    if (callee == null || callee.getMethod() == null) {
                        throw checkpointRefusal("java-checkpoint-unresolved-741");
                    }
                    MethodReference target = callee.getMethod();
                    if (runtime && progressRuntimeClassIdentity(target.getClassName()) != null) {
                        continue; // Independently checked, source-bound ABI roots.
                    }
                    if (target.getName().equals("<clinit>")) {
                        if (!dependency.getReachableMethods().contains(target)) {
                            throw checkpointRefusal("java-checkpoint-unresolved-741");
                        }
                        // Each initializer is already an independent root.
                        // Owned C initialization sets in-progress before its
                        // body: reentrant initialization is not a recursive
                        // ordinary call. Direct invokes are rejected in the IR.
                        continue;
                    }
                    Integer targetIndex = contexts.get(target);
                    if (targetIndex == null) {
                        if (pending.size() == 65536) {
                            throw checkpointRefusal("java-checkpoint-analysis-bound-741");
                        }
                        targetIndex = pending.size();
                        contexts.put(target, targetIndex);
                        pending.add(target);
                    }
                    edges.add(new int[] { index, targetIndex });
                }
            }
        }
        if (pending.isEmpty()) {
            return;
        }
        org.teavm.common.GraphBuilder builder = new org.teavm.common.GraphBuilder(pending.size());
        for (int[] edge : edges) {
            builder.addEdge(edge[0], edge[1]);
        }
        org.teavm.common.Graph calls = builder.build();
        for (int[] component : org.teavm.common.GraphUtils.findStronglyConnectedComponents(calls)) {
            boolean cyclic = component.length > 1;
            if (!cyclic && component.length == 1) {
                for (int target : calls.outgoingEdges(component[0])) {
                    cyclic |= target == component[0];
                }
            }
            if (!cyclic || pinnedStringCopyCycle(component, pending)) {
                continue;
            }
            // Generic recursive calls have no inferred depth argument. Only
            // the closed ABI's decreasing-dimension/bounded-arena families may
            // establish such an argument; an async label does not establish it.
            for (int member : component) {
                MethodReference reference = pending.get(member);
                ClassReader cls = classSource.get(reference.getClassName());
                MethodReader method = cls == null ? null : cls.getMethod(reference.getDescriptor());
                if (method == null || !finiteRuntimeMethod(cls, method)) {
                    throw checkpointRefusal("java-checkpoint-nonsuspendable-progress-741");
                }
            }
        }
    }

    private boolean pinnedStringCopyCycle(int[] component, java.util.List<MethodReference> methods) {
        org.teavm.model.ValueType object = org.teavm.model.ValueType.object("java.lang.Object");
        org.teavm.model.ValueType integer = org.teavm.model.ValueType.INTEGER;
        MethodReference constructor = new MethodReference("java.lang.String", "<init>",
                org.teavm.model.ValueType.arrayOf(org.teavm.model.ValueType.CHARACTER),
                org.teavm.model.ValueType.VOID);
        MethodReference copy = new MethodReference("java.lang.System", "arraycopy", object, integer,
                object, integer, integer, org.teavm.model.ValueType.VOID);
        if (component.length != 2 || !(methods.get(component[0]).equals(constructor)
                && methods.get(component[1]).equals(copy) || methods.get(component[1]).equals(constructor)
                && methods.get(component[0]).equals(copy))) {
            return false;
        }
        // Error-message materialization creates this apparent cycle. The exact
        // char[] constructor always copies a non-null array into its freshly
        // allocated equal-length char[] at offset zero. That nested arraycopy
        // cannot take the error/string-materialization branch again. All other
        // Java callees remain in the ordinary bounded closure above.
        try {
            return pinnedProgressPlatformMethod(constructor, "org.teavm.classlib.java.lang.TString", true)
                    && pinnedProgressPlatformMethod(copy, "org.teavm.classlib.java.lang.TSystem", true);
        } catch (Exception unavailable) {
            return false;
        }
    }

    private boolean pinnedAbsentRuntimeInitializer(ClassReader actual, MethodReference reference) {
        if (actual == null || progressRuntimeClassIdentity(actual.getName()) == null
                || !reference.getDescriptor().equals(new org.teavm.model.MethodDescriptor("<clinit>",
                        org.teavm.model.ValueType.VOID))
                || actual.getMethod(reference.getDescriptor()) != null) {
            return false;
        }
        try {
            org.teavm.model.ClassHolder original = originalProgressClass(actual.getName());
            return original != null && original.getMethod(reference.getDescriptor()) == null
                    && progressLayout(actual.getName(), new java.util.HashSet<>());
        } catch (Exception unavailable) {
            return false;
        }
    }

    private java.security.MessageDigest progressDigest() {
        try {
            return java.security.MessageDigest.getInstance("SHA-256");
        } catch (java.security.NoSuchAlgorithmException unavailable) {
            throw new IllegalStateException("java-checkpoint-unresolved-741", unavailable);
        }
    }

    private boolean sameProgressMetadata(ClassReader expected, ClassReader actual) throws java.io.IOException {
        if (expected.getMethods().size() != actual.getMethods().size()
                || expected.getFields().size() != actual.getFields().size()) {
            return false;
        }
        org.teavm.model.ClassHolder left = progressMetadata(expected);
        org.teavm.model.ClassHolder right = progressMetadata(actual);
        org.teavm.cache.ClassIO io = new org.teavm.cache.ClassIO(new org.teavm.model.ReferenceCache(),
                new org.teavm.cache.InMemorySymbolTable(), new org.teavm.cache.InMemorySymbolTable(),
                new org.teavm.cache.InMemorySymbolTable());
        java.security.MessageDigest first = progressDigest(), second = progressDigest();
        // One serializer and shared tables are essential: a changed field or
        // operand cannot acquire the same independently assigned symbol ID.
        // Streaming keeps the representation out of memory and public output.
        try (java.security.DigestOutputStream a = new java.security.DigestOutputStream(
                    java.io.OutputStream.nullOutputStream(), first);
                java.security.DigestOutputStream b = new java.security.DigestOutputStream(
                    java.io.OutputStream.nullOutputStream(), second)) {
            io.writeClass(a, left);
            io.writeClass(b, right);
        }
        return java.security.MessageDigest.isEqual(first.digest(), second.digest());
    }

    private org.teavm.model.ClassHolder progressMetadata(ClassReader source) {
        // ModelUtils.copyClass(..., false) still calls getProgram() before its
        // boolean check. Do not force unreachable programme suppliers during a
        // final-reachability proof. Copy declarations without ever asking them.
        org.teavm.model.ClassHolder result = new org.teavm.model.ClassHolder(source.getName());
        result.setLevel(source.getLevel());
        result.getModifiers().addAll(source.readModifiers());
        result.setParent(source.getParent());
        result.setGenericParent(source.getGenericParent());
        result.getInterfaces().addAll(source.getInterfaces());
        result.getGenericInterfaces().addAll(source.getGenericInterfaces());
        result.setGenericParameters(source.getGenericParameters());
        result.setOwnerName(source.getOwnerName());
        result.setDeclaringClassName(source.getDeclaringClassName());
        result.setSimpleName(source.getSimpleName());
        result.getInnerClasses().addAll(source.getInnerClasses());
        ModelUtils.copyAnnotations(source.getAnnotations(), result.getAnnotations());
        for (org.teavm.model.FieldReader field : source.getFields()) {
            result.addField(ModelUtils.copyField(field));
        }
        for (MethodReader method : source.getMethods()) {
            org.teavm.model.MethodHolder copy = new org.teavm.model.MethodHolder(method.getDescriptor());
            copy.setLevel(method.getLevel());
            copy.getModifiers().addAll(method.readModifiers());
            copy.setTypeParameters(method.getTypeParameters());
            copy.setGenericSignature(method.getGenericResultType(), method.getGenericParameterTypes());
            ModelUtils.copyAnnotations(method.getAnnotations(), copy.getAnnotations());
            if (method.getAnnotationDefault() != null) {
                // ClassIO only reads the default; do not mutate the final source
                // or call ModelUtils' private annotation-value copier.
                copy.setAnnotationDefault(method.getAnnotationDefault());
            }
            for (int index = 0; index < method.parameterCount(); ++index) {
                ModelUtils.copyAnnotations(method.parameterAnnotation(index), copy.parameterAnnotation(index));
            }
            copy.setThrownTypes(method.getThrownTypes());
            result.addMethod(copy);
        }
        return result;
    }

    private boolean sameProgressBody(ProgramReader expected, ProgramReader actual) throws java.io.IOException {
        if (expected == null || actual == null) {
            return expected == actual;
        }
        org.teavm.model.Program first = boundedProgressProgram(expected);
        org.teavm.model.Program second = boundedProgressProgram(actual);
        if (first == null || second == null) {
            return false;
        }
        org.teavm.cache.ProgramIO io = new org.teavm.cache.ProgramIO(new org.teavm.model.ReferenceCache(),
                new org.teavm.cache.InMemorySymbolTable(), new org.teavm.cache.InMemorySymbolTable(),
                new org.teavm.cache.InMemorySymbolTable());
        java.security.MessageDigest left = progressDigest(), right = progressDigest();
        try (java.security.DigestOutputStream a = new java.security.DigestOutputStream(
                    java.io.OutputStream.nullOutputStream(), left);
                java.security.DigestOutputStream b = new java.security.DigestOutputStream(
                    java.io.OutputStream.nullOutputStream(), right)) {
            io.write(first, a);
            io.write(second, b);
        }
        return java.security.MessageDigest.isEqual(left.digest(), right.digest());
    }

    private final java.util.Map<MethodReference, Boolean> progressRuntimeProofs = new java.util.HashMap<>();

    private boolean finiteRuntimeMethod(ClassReader actualClass, MethodReader actualMethod) {
        Boolean cached = progressRuntimeProofs.get(actualMethod.getReference());
        if (cached != null) {
            return cached;
        }
        boolean result = proveFiniteRuntimeMethod(actualClass, actualMethod);
        progressRuntimeProofs.put(actualMethod.getReference(), result);
        return result;
    }

    private boolean proveFiniteRuntimeMethod(ClassReader actualClass, MethodReader actualMethod) {
        // This proof assumes the unchanged owned C/OWN_GC ABI and a valid heap.
        // It does not establish safety of arbitrary native imports/raw writes.
        // Those interfaces are neither expanded nor silently approved here.
        if (progressRuntimeClassIdentity(actualClass.getName()) == null) {
            return false;
        }
        try {
            org.teavm.model.ClassHolder original = originalProgressClass(actualClass.getName());
            if (original == null) {
                return false;
            }
            org.teavm.model.ClassHolder expectedClass = ModelUtils.copyClass(original);
            new org.teavm.backend.c.analyze.CDependencyListener().transformClass(expectedClass, null);
            if (!sameProgressMetadata(expectedClass, actualClass)) {
                return false;
            }
            org.teavm.model.MethodHolder expected = expectedClass.getMethod(actualMethod.getDescriptor());
            if (expected == null) {
                return false;
            }
            org.teavm.model.Program program = expected.getProgram();
            if (program != null) {
                org.teavm.diagnostics.AccumulationDiagnostics diagnostics =
                        new org.teavm.diagnostics.AccumulationDiagnostics();
                String[] platforms = { org.teavm.interop.Platforms.C,
                        org.teavm.interop.Platforms.LOW_LEVEL, org.teavm.interop.Platforms.OWN_GC };
                if (!progressPlatformMarkers(expectedClass, diagnostics)) {
                    return false;
                }
                org.teavm.dependency.ReferenceResolver resolver = new org.teavm.dependency.ReferenceResolver(
                        dependency.getClassSource(), platforms, diagnostics);
                resolver.use(expected.getReference());
                resolver.resolve(expected, program);
                if (!diagnostics.getSevereProblems().isEmpty()) {
                    return false;
                }
                new org.teavm.model.transformation.ClassInitInsertion(dependency.getClassSource()).apply(expected, program);
            }
            return progressLayouts(actualClass, expected, program)
                    && sameProgressBody(program, actualMethod.getProgram());
        } catch (Exception unavailable) {
            return false; // Missing proof is an explicit unsupported classification.
        }
    }

    private boolean progressPlatformMarkers(org.teavm.model.ClassHolder expected,
            org.teavm.diagnostics.AccumulationDiagnostics diagnostics) throws Exception {
        org.teavm.model.ClassHolderSource hierarchy = originalProgressHierarchy();
        if (hierarchy == null) {
            return false;
        }
        // Only these two public context queries occur in the pinned class pass.
        // A lambda/JDK proxy preserves the original three-class finder output;
        // no anonymous or new nested companion is admitted to the compiler JAR.
        org.teavm.model.ClassHierarchy markers = new org.teavm.model.ClassHierarchy(hierarchy);
        org.teavm.model.ClassHolderTransformerContext context =
                (org.teavm.model.ClassHolderTransformerContext) java.lang.reflect.Proxy.newProxyInstance(
                        AsyncMethodFinder.class.getClassLoader(),
                        new Class<?>[] { org.teavm.model.ClassHolderTransformerContext.class },
                        (proxy, member, arguments) -> {
                            if (member.getDeclaringClass() != org.teavm.model.ClassHolderTransformerContext.class
                                    || member.getParameterCount() != 0) {
                                throw new UnsupportedOperationException("unexpected-progress-transform-context");
                            }
                            switch (member.getName()) {
                                case "getHierarchy": return markers;
                                case "getDiagnostics": return diagnostics;
                                default: throw new UnsupportedOperationException("unexpected-progress-transform-context");
                            }
                        });
        new org.teavm.classlib.impl.PlatformMarkerSupport(new String[] { org.teavm.interop.Platforms.C,
                org.teavm.interop.Platforms.LOW_LEVEL, org.teavm.interop.Platforms.OWN_GC })
                .transformClass(expected, context);
        return diagnostics.getSevereProblems().isEmpty();
    }

    private final java.util.Map<String, org.teavm.model.ClassHolder> progressOriginalClasses = new java.util.HashMap<>();
    private final java.util.Map<String, Boolean> progressMetadataProofs = new java.util.HashMap<>();

    private org.teavm.model.ClassHolder originalProgressClass(String name) throws Exception {
        org.teavm.model.ClassHolder cached = progressOriginalClasses.get(name);
        if (cached != null) {
            return cached;
        }
        String identity = progressRuntimeClassIdentity(name);
        if (identity == null) {
            identity = progressDonorIdentity(name);
        }
        if (identity == null) {
            return null;
        }
        Class<?> host = Class.forName(name, false, AsyncMethodFinder.class.getClassLoader());
        if (host.getClassLoader() != AsyncMethodFinder.class.getClassLoader()) {
            return null;
        }
        java.nio.file.Path jar = java.nio.file.Path.of(host.getProtectionDomain()
                .getCodeSource().getLocation().toURI()).toRealPath();
        if (!java.nio.file.Files.isRegularFile(jar, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                || java.nio.file.Files.size(jar) > 67108864) {
            return null;
        }
        try (java.util.zip.ZipFile zip = new java.util.zip.ZipFile(jar.toFile())) {
            java.util.zip.ZipEntry entry = zip.getEntry(name.replace('.', '/') + ".class");
            if (entry == null || entry.getSize() <= 0 || entry.getSize() > 131072) {
                return null;
            }
            byte[] bytes;
            try (java.io.InputStream input = zip.getInputStream(entry)) {
                bytes = input.readNBytes(131073);
            }
            if (bytes.length != entry.getSize()) {
                return null;
            }
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder hex = new StringBuilder(64);
            for (byte value : digest) {
                hex.append(Character.forDigit((value >>> 4) & 15, 16));
                hex.append(Character.forDigit(value & 15, 16));
            }
            if (!identity.equals(hex.toString())) {
                return null;
            }
        }
        try (org.teavm.parsing.resource.ResourceProvider provider =
                org.teavm.parsing.resource.ResourceProvider.ofClassPath(
                        java.util.Collections.singletonList(jar.toFile()))) {
            org.teavm.model.ClassHolderSource source = new org.teavm.model.PreOptimizingClassHolderSource(
                    new org.teavm.parsing.resource.ResourceBytecodeClassHolderSource(provider,
                            new org.teavm.model.ReferenceCache()));
            org.teavm.model.ClassHolder result = source.get(name);
            if (result == null || result.getMethods().size() > 65536 || result.getFields().size() > 65536) {
                return null;
            }
            // These are immutable original programmes, not dependency suppliers.
            // Materialize them while their authenticated provider is open.
            for (org.teavm.model.MethodHolder method : result.getMethods()) {
                if (method.getProgram() != null && boundedProgressProgram(method.getProgram()) == null) {
                    return null;
                }
            }
            progressOriginalClasses.put(name, result);
            return result;
        }
    }

    private org.teavm.model.ClassHolderSource originalProgressHierarchy() throws Exception {
        org.teavm.model.MutableClassHolderSource result = new org.teavm.model.MutableClassHolderSource();
        for (String name : progressRuntimeClassNames()) {
            org.teavm.model.ClassHolder cls = originalProgressClass(name);
            if (cls == null) {
                return null;
            }
            result.putClassHolder(cls);
        }
        return result;
    }

    private boolean progressLayout(String name, java.util.Set<String> visited) throws Exception {
        if (name == null || progressRuntimeClassIdentity(name) == null || !visited.add(name)) {
            return true;
        }
        if (visited.size() > 65536) {
            return false;
        }
        org.teavm.model.ClassHolder baseline = originalProgressClass(name);
        // Native ABI types may be absent from the executable class view. The
        // unfiltered transformed declaration still must match its pinned layout.
        ClassReader actual = dependency.getClassSource().get(name);
        if (baseline == null || actual == null) {
            return false; // A required semantic layout is never treated as optional.
        }
        Boolean cached = progressMetadataProofs.get(name);
        if (cached == null) {
            org.teavm.model.ClassHolder expected = ModelUtils.copyClass(baseline);
            new org.teavm.backend.c.analyze.CDependencyListener().transformClass(expected, null);
            cached = sameProgressMetadata(expected, actual);
            progressMetadataProofs.put(name, cached);
        }
        if (!cached || !progressLayout(baseline.getParent(), visited)) {
            return false;
        }
        for (String parent : baseline.getInterfaces()) {
            if (!progressLayout(parent, visited)) {
                return false;
            }
        }
        return true;
    }

    private boolean progressLayoutType(org.teavm.model.ValueType type, java.util.Set<String> visited)
            throws Exception {
        int dimensions = 0;
        while (type instanceof org.teavm.model.ValueType.Array) {
            if (++dimensions > 255) {
                return false;
            }
            type = ((org.teavm.model.ValueType.Array) type).getItemType();
        }
        return !(type instanceof org.teavm.model.ValueType.Object)
                || progressLayout(((org.teavm.model.ValueType.Object) type).getClassName(), visited);
    }

    private boolean progressLayouts(ClassReader owner, MethodReader method,
            org.teavm.model.Program program) throws Exception {
        java.util.Set<String> visited = new java.util.HashSet<>();
        if (!progressLayout(owner.getName(), visited)) {
            return false;
        }
        for (org.teavm.model.ValueType type : method.getSignature()) {
            if (!progressLayoutType(type, visited)) {
                return false;
            }
        }
        if (program == null) {
            return true;
        }
        // Follow actual semantic layout uses, including data-only classes.
        // Merely mentioned pointer/signature types do not force absent DCE
        // classes into a lean programme. Required loads/sizeof literals do.
        for (org.teavm.model.BasicBlock block : program.getBasicBlocks()) {
            for (org.teavm.model.Instruction instruction : block) {
                if (instruction instanceof org.teavm.model.instructions.ClassConstantInstruction) {
                    if (!progressLayoutType(((org.teavm.model.instructions.ClassConstantInstruction) instruction)
                            .getConstant(), visited)) {
                        return false;
                    }
                } else if (instruction instanceof org.teavm.model.instructions.GetFieldInstruction) {
                    if (!progressLayout(((org.teavm.model.instructions.GetFieldInstruction) instruction)
                            .getField().getClassName(), visited)) {
                        return false;
                    }
                } else if (instruction instanceof org.teavm.model.instructions.PutFieldInstruction) {
                    if (!progressLayout(((org.teavm.model.instructions.PutFieldInstruction) instruction)
                            .getField().getClassName(), visited)) {
                        return false;
                    }
                } else if (instruction instanceof org.teavm.model.instructions.InvokeInstruction) {
                    if (!progressLayout(((org.teavm.model.instructions.InvokeInstruction) instruction)
                            .getMethod().getClassName(), visited)) {
                        return false;
                    }
                } else if (instruction instanceof org.teavm.model.instructions.ConstructInstruction) {
                    if (!progressLayout(((org.teavm.model.instructions.ConstructInstruction) instruction)
                            .getType(), visited)) {
                        return false;
                    }
                }
            }
        }
        return true;
    }

    private String progressRuntimeClassIdentity(String name) {
        switch (name) {
            case "org.teavm.backend.c.runtime.Memory": return "93200eea452324cb61e280b375ef713a02c75c4e8cd265a0a35ccd71ca9d560c";
            case "org.teavm.classlib.PlatformDetector": return "fed9f02822ccbbb9ff0f897a2047748d76f34d35c6c417223f9aeb6f3b9105bb";
            case "org.teavm.interop.Address": return "b8e1527375e7e90046468f66e68861db1a46d5bd65458be1d62614789eafff42";
            case "org.teavm.interop.Structure": return "af925539c3d835e9b61d35f7fb1e65ac49c0a38a47ba8d3a81d4269400559276";
            case "org.teavm.runtime.Allocator": return "6aee4d703cbea530313ca5f267733dc6b745a859265fbad555604559674a659c";
            case "org.teavm.runtime.CallSite": return "05fc8fa5768fba2d1c38bea423c63ce923b544a15d4ce93cf6805caf5d9c4df2";
            case "org.teavm.runtime.CallSiteLocation": return "603e649cf133e2ffa87863d60e2d40464928c078797b1c99dc732219032a0347";
            case "org.teavm.runtime.Console": return "30175d7bef95b072ef95eba0d782d143e3b71871c879f43d0e0b819e83e91fca";
            case "org.teavm.runtime.ExceptionHandler": return "819a544aa4fb5adfd6799edd83db89153bc9fec974628adf80c32c0c12f0c983";
            case "org.teavm.runtime.ExceptionHandling": return "dd79c9f2c7d9e5d216b2ef9feae8a0a192c35f2650dd355b5db84be8890e208e";
            case "org.teavm.runtime.FreeChunk": return "4fda9381ed5165223e9c39201defbf119098223fe41298c67c9d3b78615cb61b";
            case "org.teavm.runtime.FreeChunkHolder": return "268786d0bcbc27818a868b866d7ff3b5c022c511892c43672f8a0d571a0de55a";
            case "org.teavm.runtime.GC": return "14abf4b0595f4ac4cca1c34f39995f5899c0d6f4afb03ffddb4dde0b23500475";
            case "org.teavm.runtime.GC$Region": return "fffd15ad1fbe7ab24d0ce393279219d87825dbcc0f4a6c8a97dd802890c43660";
            case "org.teavm.runtime.InitFunction": return "12e0b2df07761272e3847e47d40aa73626ec770db3a88aa2d365c544cef33c99";
            case "org.teavm.runtime.IsSupertypeFunction": return "a38e353d1a06f7e3ae09f6d41f9c1f9019644377624bde6437599426414e1748";
            case "org.teavm.runtime.MarkQueue": return "51e2aa1c4e7edb166fa8eff6a07598a8bf8212fd258ccf332ae38e3c28656166";
            case "org.teavm.runtime.MemoryTrace": return "c1b12afdd2d2a1f8901c3885060afbc961e2138bc12b076a0a74ba3ae08c5bff";
            case "org.teavm.runtime.MethodLocation": return "292cbeba6e38c2471fc0445e0f765ed74b38c346a27280c15664204faf473dbc";
            case "org.teavm.runtime.Mutator": return "a7001bfa2d5ba6b975c08cd0b69c171c07631e87630ce7a90edebc4a0c831276";
            case "org.teavm.runtime.Relocation": return "227497a42dee6bd7e5a8c43ec1386ce671c0d48ed5d59716fe4d2f537a790e67";
            case "org.teavm.runtime.RelocationBlock": return "c3ea30ce56c17f24a44beb2fab8eeca1d61a99dafd9269f3dea7230b7b7737d6";
            case "org.teavm.runtime.RuntimeArray": return "077ec8f50819009bada9f2e7b72a087a5681fd29a8fb7974d50d1ec0b0900d77";
            case "org.teavm.runtime.RuntimeBuffer": return "fd501c9ed10b1178c6665dc49b0c71b27b67eff3c09ad11409a2557bbeb43cd6";
            case "org.teavm.runtime.RuntimeClass": return "2421efdefa1fbd747d7c6d9768ee61fddb3ec5916da1cc7cdd2e8df50e524490";
            case "org.teavm.runtime.RuntimeClassPointer": return "fcbd6ffd919a831afa407434105974821d0fd3c8503acb5015d09bc9b20ed9e7";
            case "org.teavm.runtime.RuntimeObject": return "24837e328b70cb0780e1c1586b21a2e223604424e5f67dc795fe935d78ce6ce6";
            case "org.teavm.runtime.RuntimeObjectPtr": return "eb7ee52a682c0d3ef4285d0c7bbfc9c7374132283949cce24817d7d82b18486d";
            case "org.teavm.runtime.RuntimeReference": return "e3bfbc56b6a311546e915f608b4ad4b731e8e529fd43ff5e6111ac8b13464a68";
            case "org.teavm.runtime.RuntimeReferenceQueue": return "324b71917901093897b287d9a42dd0ab967f4a3d8abfbcdf3afd1ba31a4b91b5";
            case "org.teavm.runtime.ShadowStack": return "edb8ab34aab3d48c42b00a597d1a6c7335bb8d387103f52f8841a8b501e57b31";
            case "org.teavm.runtime.StringPtr": return "5f5eaf0275b37b9765ab676034b9b7b7a2452d9738107be000d5f8e7d931629d";
            default: return null;
        }
    }

    private String[] progressRuntimeClassNames() {
        return new String[] {
            "org.teavm.runtime.StringPtr",
            "org.teavm.backend.c.runtime.Memory",
            "org.teavm.classlib.PlatformDetector",
            "org.teavm.interop.Address",
            "org.teavm.interop.Structure",
            "org.teavm.runtime.Allocator",
            "org.teavm.runtime.CallSite",
            "org.teavm.runtime.CallSiteLocation",
            "org.teavm.runtime.Console",
            "org.teavm.runtime.ExceptionHandler",
            "org.teavm.runtime.ExceptionHandling",
            "org.teavm.runtime.FreeChunk",
            "org.teavm.runtime.FreeChunkHolder",
            "org.teavm.runtime.GC",
            "org.teavm.runtime.GC$Region",
            "org.teavm.runtime.InitFunction",
            "org.teavm.runtime.IsSupertypeFunction",
            "org.teavm.runtime.MarkQueue",
            "org.teavm.runtime.MemoryTrace",
            "org.teavm.runtime.MethodLocation",
            "org.teavm.runtime.Mutator",
            "org.teavm.runtime.Relocation",
            "org.teavm.runtime.RelocationBlock",
            "org.teavm.runtime.RuntimeArray",
            "org.teavm.runtime.RuntimeBuffer",
            "org.teavm.runtime.RuntimeClass",
            "org.teavm.runtime.RuntimeClassPointer",
            "org.teavm.runtime.RuntimeObject",
            "org.teavm.runtime.RuntimeObjectPtr",
            "org.teavm.runtime.RuntimeReference",
            "org.teavm.runtime.RuntimeReferenceQueue",
            "org.teavm.runtime.ShadowStack"
        };
    }

    private boolean progressDelegateType(org.teavm.model.ValueType from, org.teavm.model.ValueType to)
            throws Exception {
        if (from.equals(to)) {
            return true;
        }
        // The unchanged C ABI has explicit managed/native object/array headers.
        // Do not treat arbitrary references, integers or function pointers as
        // interchangeable merely because wasm32 represents them in one word.
        // This is representation compatibility, not proof that an arbitrary
        // raw argument satisfies the owned ABI's valid-object/array precondition.
        org.teavm.model.ValueType object = org.teavm.model.ValueType.object("java.lang.Object");
        for (String name : new String[] { "org.teavm.runtime.RuntimeObject", "org.teavm.runtime.RuntimeArray" }) {
            org.teavm.model.ValueType header = org.teavm.model.ValueType.object(name);
            if ((from.equals(object) && to.equals(header) || from.equals(header) && to.equals(object))
                    && progressLayout(name, new java.util.HashSet<>())) {
                return true;
            }
        }
        return false;
    }

    private MethodReference progressNativeDelegate(ClassReader cls, MethodReader method) {
        MethodReference classObject = new MethodReference("org.teavm.runtime.reflect.ClassInfo", "classObject",
                org.teavm.model.ValueType.object("java.lang.Class"));
        if (method.getReference().equals(classObject) && method.hasModifier(ElementModifier.NATIVE)
                && !method.hasModifier(ElementModifier.STATIC) && pinnedClassMetadataMethod(method)) {
            // The owned C helper is a cache lookup and at most one call to
            // Class.createClass. Prove that Java helper transitively, rather
            // than granting every reflective/initialization native a pass.
            MethodReference target = new MethodReference("java.lang.Class", "createClass",
                    org.teavm.model.ValueType.object("org.teavm.runtime.reflect.ClassInfo"),
                    org.teavm.model.ValueType.object("java.lang.Class"));
            return dependency.getReachableMethods().contains(target) ? target : null;
        }
        org.teavm.model.AnnotationReader declaration = method.getAnnotations().get("org.teavm.interop.DelegateTo");
        if (!method.hasModifier(ElementModifier.NATIVE) || declaration == null
                || method.getAnnotations().get("org.teavm.interop.Import") != null) {
            return null;
        }
        try {
            org.teavm.model.AnnotationValue value = declaration.getValue("value");
            String name = value == null ? null : value.getString();
            if (name == null || name.isEmpty() || name.length() > 65535
                    || name.equals("<init>") || name.equals("<clinit>")
                    || name.equals(method.getName())) {
                return null;
            }
            MethodReader target = null;
            int count = 0;
            for (MethodReader candidate : cls.getMethods()) {
                if (++count > 65536) {
                    return null;
                }
                if (candidate.getName().equals(name)) {
                    if (target != null) {
                        return null; // C's name-selected delegate must be unambiguous.
                    }
                    target = candidate;
                }
            }
            int receiver = method.hasModifier(ElementModifier.STATIC) ? 0 : 1;
            if (target == null || !target.hasModifier(ElementModifier.STATIC)
                    || target.parameterCount() != method.parameterCount() + receiver
                    || !progressDelegateType(target.getResultType(), method.getResultType())) {
                return null;
            }
            if (receiver != 0 && !progressDelegateType(org.teavm.model.ValueType.object(cls.getName()),
                    target.parameterType(0))) {
                return null;
            }
            for (int index = 0; index < method.parameterCount(); ++index) {
                if (!progressDelegateType(method.parameterType(index), target.parameterType(index + receiver))) {
                    return null;
                }
            }
            return dependency.getReachableMethods().contains(target.getReference()) ? target.getReference() : null;
        } catch (Exception unavailable) {
            return null;
        }
    }

    private String progressDonorIdentity(String name) {
        switch (name) {
            case "org.teavm.classlib.java.lang.TObject":
                return "dc3ef8b117975faf357bd6c9cdb772df390e914c8f3d82f1265af0b752c61651";
            case "org.teavm.classlib.java.lang.TStackTraceElement":
                return "9ba416fd3d6ab3503eb37b937fa1155ffdfc64012de17573e733ef6af20b74f9";
            case "org.teavm.classlib.java.lang.TInteger":
                return "ab971343646fcb1d75fb67cad2720de7c7ec1f270b93ba29892b17d157a37c11";
            case "org.teavm.classlib.java.lang.TLong":
                return "c52aba5c1d8856119fb9e4d3792487329f6a3f09d3c7c85badb220759eb6d856";
            case "org.teavm.classlib.java.lang.TFloat":
                return "be7d539a56499183397f76e5f416cdf6fc5eea85df127c3d2da857787b956327";
            case "org.teavm.classlib.java.lang.TDouble":
                return "a5d1be085669ed38036ca649f481cf11721a6921528af0ea4edf913c3e13e52f";
            case "org.teavm.runtime.reflect.ClassInfo":
                return "8ce9a2e2d304c3b8cf0f5ae81a1d8644931a00e2316057ca0b6f2ab634394d18";
            case "org.teavm.runtime.reflect.ReflectionInfo":
                return "a746e0d136e4d2d9ba83a3be093d0b2c1616eec58419402d01b7fcb483aaab5a";
            case "org.teavm.classlib.java.lang.TString":
                return "f8920b4fd19dfa052d65646bf146065f90656c01e2feb4a8d72eb2e07cdabd67";
            case "org.teavm.classlib.java.lang.TSystem":
                return "6a433de9184331e5497d1e5a42aa5ba6fe4ff2e9c63f9b7c29312d3e00b7a746";
            default: return null;
        }
    }

    private boolean closedRuntimeCalls(ProgramReader reader) throws Exception {
        if (reader == null) {
            return true; // The fixed ABI's declared native primitives have their finite argument.
        }
        org.teavm.model.Program program = boundedProgressProgram(reader);
        if (program == null) {
            return false;
        }
        for (org.teavm.model.BasicBlock block : program.getBasicBlocks()) {
            for (org.teavm.model.Instruction instruction : block) {
                if (!(instruction instanceof org.teavm.model.instructions.InvokeInstruction)) {
                    continue;
                }
                MethodReference target = ((org.teavm.model.instructions.InvokeInstruction) instruction).getMethod();
                if (progressRuntimeClassIdentity(target.getClassName()) == null
                        && !progressPlatformConstructor(target)) {
                    return false;
                }
            }
        }
        return true;
    }

    private final java.util.Map<MethodReference, Boolean> progressPlatformProofs = new java.util.HashMap<>();

    private boolean progressPlatformConstructor(MethodReference reference) throws Exception {
        String donor;
        if (reference.equals(new MethodReference("java.lang.Object", "<init>", org.teavm.model.ValueType.VOID))) {
            donor = "org.teavm.classlib.java.lang.TObject";
        } else if (reference.equals(new MethodReference("java.lang.StackTraceElement", "<init>",
                org.teavm.model.ValueType.object("java.lang.String"), org.teavm.model.ValueType.object("java.lang.String"),
                org.teavm.model.ValueType.object("java.lang.String"), org.teavm.model.ValueType.INTEGER,
                org.teavm.model.ValueType.VOID))) {
            donor = "org.teavm.classlib.java.lang.TStackTraceElement";
        } else {
            return false;
        }
        return pinnedProgressPlatformMethod(reference, donor,
                reference.getClassName().equals("java.lang.StackTraceElement"));
    }

    private boolean pinnedProgressPlatformMethod(MethodReference reference, String donor,
            boolean completeDeclaration) throws Exception {
        Boolean cached = progressPlatformProofs.get(reference);
        if (cached != null) {
            return cached;
        }
        if (originalProgressClass(donor) == null) {
            return false;
        }
        java.util.List<java.io.File> jars = new java.util.ArrayList<>();
        for (String name : new String[] { "org.teavm.runtime.GC", "org.teavm.interop.Address", donor }) {
            Class<?> host = Class.forName(name, false, AsyncMethodFinder.class.getClassLoader());
            java.nio.file.Path path = java.nio.file.Path.of(host.getProtectionDomain()
                    .getCodeSource().getLocation().toURI()).toRealPath();
            if (!jars.contains(path.toFile())) {
                jars.add(path.toFile());
            }
        }
        boolean result = false;
        try (org.teavm.parsing.resource.ResourceProvider provider =
                org.teavm.parsing.resource.ResourceProvider.ofClassPath(jars)) {
            org.teavm.model.ReferenceCache cache = new org.teavm.model.ReferenceCache();
            org.teavm.model.ClassHolderSource bytes =
                    new org.teavm.parsing.resource.ResourceBytecodeClassHolderSource(provider, cache);
            org.teavm.parsing.substitution.SubstituteClassNameMapping mapping =
                    org.teavm.parsing.substitution.DefaultSubstituteClassNameMapping.createWithPolicies(
                            java.util.Collections.singletonList(new org.teavm.classlib.impl.ClasslibSubstitutionPolicy()));
            org.teavm.model.ClassHolderSource source = new org.teavm.model.PreOptimizingClassHolderSource(
                    new org.teavm.parsing.RenamingClassHolderSource(provider, cache, bytes, mapping));
            org.teavm.model.ClassHolder cls = source.get(reference.getClassName());
            if (cls != null) {
                new org.teavm.backend.c.analyze.CDependencyListener().transformClass(cls, null);
                new org.teavm.classlib.impl.string.DefaultStringTransformer().transformClass(cls, null);
            }
            org.teavm.model.MethodHolder expected = cls == null ? null : cls.getMethod(reference.getDescriptor());
            ClassReader actualClass = dependency.getClassSource().get(reference.getClassName());
            MethodReader actual = actualClass == null ? null : actualClass.getMethod(reference.getDescriptor());
            if (expected != null && actual != null) {
                if (completeDeclaration && !sameProgressMetadata(cls, actualClass)) {
                    return false;
                }
                org.teavm.model.ClassHolder left = new org.teavm.model.ClassHolder(reference.getClassName());
                org.teavm.model.ClassHolder right = new org.teavm.model.ClassHolder(reference.getClassName());
                left.addMethod(ModelUtils.copyMethod(expected));
                right.addMethod(ModelUtils.copyMethod(actual));
                org.teavm.diagnostics.AccumulationDiagnostics diagnostics =
                        new org.teavm.diagnostics.AccumulationDiagnostics();
                if (!progressPlatformMarkers(cls, diagnostics)) {
                    return false;
                }
                if (expected.getProgram() != null) {
                    org.teavm.dependency.ReferenceResolver resolver = new org.teavm.dependency.ReferenceResolver(
                            dependency.getClassSource(), new String[] { org.teavm.interop.Platforms.C,
                                    org.teavm.interop.Platforms.LOW_LEVEL, org.teavm.interop.Platforms.OWN_GC }, diagnostics);
                    resolver.use(expected.getReference());
                    resolver.resolve(expected, expected.getProgram());
                    new org.teavm.model.transformation.ClassInitInsertion(dependency.getClassSource()).apply(expected, expected.getProgram());
                }
                result = diagnostics.getSevereProblems().isEmpty() && sameProgressMetadata(left, right)
                        && sameProgressBody(expected.getProgram(), actual.getProgram());
            }
        }
        progressPlatformProofs.put(reference, result);
        return result;
    }

    private boolean progressClassMetadataPrimitive(MethodReader method) {
        String owner = "org.teavm.runtime.reflect.ClassInfo";
        if (!method.getReference().getClassName().equals(owner)
                || !method.hasModifier(ElementModifier.NATIVE)
                || method.hasModifier(ElementModifier.STATIC)
                || method.getAnnotations().get("org.teavm.interop.Unmanaged") == null
                || method.getAnnotations().get("org.teavm.interop.Intrinsified") == null) {
            return false;
        }
        org.teavm.model.ValueType integer = org.teavm.model.ValueType.INTEGER;
        org.teavm.model.ValueType info = org.teavm.model.ValueType.object(owner);
        org.teavm.model.MethodDescriptor shape;
        switch (method.getName()) {
            case "modifiers": case "primitiveKind": case "superinterfaceCount":
                shape = new org.teavm.model.MethodDescriptor(method.getName(), integer);
                break;
            case "itemType": case "declaringClass": case "enclosingClass": case "parent":
                shape = new org.teavm.model.MethodDescriptor(method.getName(), info);
                break;
            case "name": case "simpleName":
                shape = new org.teavm.model.MethodDescriptor(method.getName(),
                        org.teavm.model.ValueType.object("org.teavm.runtime.StringInfo"));
                break;
            case "superinterface":
                shape = new org.teavm.model.MethodDescriptor(method.getName(), integer, info);
                break;
            case "arrayLength":
                shape = new org.teavm.model.MethodDescriptor(method.getName(),
                        org.teavm.model.ValueType.object("java.lang.Object"), integer);
                break;
            case "isSuperTypeOf":
                // Calls the owned compiler-generated finite type predicate,
                // not a Java callback or application class initializer.
                shape = new org.teavm.model.MethodDescriptor(method.getName(), info,
                        org.teavm.model.ValueType.BOOLEAN);
                break;
            case "reflection":
                shape = new org.teavm.model.MethodDescriptor(method.getName(),
                        org.teavm.model.ValueType.object("org.teavm.runtime.reflect.ClassReflectionInfo"));
                break;
            default: return false; // No allocation, initialization or reflective callbacks.
        }
        if (!method.getDescriptor().equals(shape)) {
            return false;
        }
        return pinnedClassMetadataMethod(method);
    }

    private boolean pinnedClassMetadataMethod(MethodReader method) {
        try {
            String owner = "org.teavm.runtime.reflect.ClassInfo";
            String parent = "org.teavm.runtime.reflect.ReflectionInfo";
            org.teavm.model.ClassHolder baseline = originalProgressClass(parent);
            ClassReader actual = dependency.getClassSource().get(parent);
            return baseline != null && actual != null && sameProgressMetadata(baseline, actual)
                    && progressLayout("org.teavm.runtime.RuntimeClass", new java.util.HashSet<>())
                    && pinnedProgressPlatformMethod(method.getReference(), owner, true);
        } catch (Exception unavailable) {
            return false;
        }
    }

    private boolean progressNativePrimitive(MethodReader method) {
        if (progressClassMetadataPrimitive(method)) {
            return true;
        }
        // These exact C operations are bounded word operations, not a general
        // approval for native methods declared by numeric-looking classes.
        org.teavm.model.ValueType integer = org.teavm.model.ValueType.INTEGER;
        org.teavm.model.ValueType longer = org.teavm.model.ValueType.LONG;
        org.teavm.model.ValueType single = org.teavm.model.ValueType.FLOAT;
        org.teavm.model.ValueType doubled = org.teavm.model.ValueType.DOUBLE;
        org.teavm.model.ValueType bool = org.teavm.model.ValueType.BOOLEAN;
        String owner = method.getReference().getClassName(), name = method.getName(), donor;
        org.teavm.model.MethodDescriptor shape = null;
        switch (owner) {
            case "java.lang.Object":
                donor = "org.teavm.classlib.java.lang.TObject";
                if (name.equals("getClassInfo")) {
                    shape = new org.teavm.model.MethodDescriptor(name,
                            org.teavm.model.ValueType.object("org.teavm.runtime.reflect.ClassInfo"));
                }
                break;
            case "java.lang.Integer":
                donor = "org.teavm.classlib.java.lang.TInteger";
                if (name.equals("divideUnsigned") || name.equals("remainderUnsigned") || name.equals("compareUnsigned")) {
                    shape = new org.teavm.model.MethodDescriptor(name, integer, integer, integer);
                }
                break;
            case "java.lang.Long":
                donor = "org.teavm.classlib.java.lang.TLong";
                if (name.equals("divideUnsigned") || name.equals("remainderUnsigned")) {
                    shape = new org.teavm.model.MethodDescriptor(name, longer, longer, longer);
                } else if (name.equals("compareUnsigned")) {
                    shape = new org.teavm.model.MethodDescriptor(name, longer, longer, integer);
                }
                break;
            case "java.lang.Float":
                donor = "org.teavm.classlib.java.lang.TFloat";
                if (name.equals("isNaN") || name.equals("isFinite")) {
                    shape = new org.teavm.model.MethodDescriptor(name, single, bool);
                } else if (name.equals("floatToRawIntBits")) {
                    shape = new org.teavm.model.MethodDescriptor(name, single, integer);
                } else if (name.equals("intBitsToFloat")) {
                    shape = new org.teavm.model.MethodDescriptor(name, integer, single);
                }
                break;
            case "java.lang.Double":
                donor = "org.teavm.classlib.java.lang.TDouble";
                if (name.equals("isNaN") || name.equals("isFinite")) {
                    shape = new org.teavm.model.MethodDescriptor(name, doubled, bool);
                } else if (name.equals("doubleToRawLongBits")) {
                    shape = new org.teavm.model.MethodDescriptor(name, doubled, longer);
                } else if (name.equals("longBitsToDouble")) {
                    shape = new org.teavm.model.MethodDescriptor(name, longer, doubled);
                }
                break;
            default: return false;
        }
        if (shape == null || !shape.equals(method.getDescriptor())) {
            return false;
        }
        try {
            return pinnedProgressPlatformMethod(method.getReference(), donor, false);
        } catch (Exception unavailable) {
            return false;
        }
    }

'''

TYPE_CLASSES = frozenset(TYPE_ROOT + name for name in (
    'TypeInferer.class', 'TypeInferer$1.class', 'TypeInferer$2.class',
    'TypeInferer$InferenceKind.class', 'TypeInferer$InferenceType.class'))
VOLATILE_ROOT = 'org/teavm/backend/c/analyze/'
VOLATILE_CLASSES = frozenset(VOLATILE_ROOT + name for name in (
    'VolatileDefinitionFinder.class', 'VolatileDefinitionFinder$1.class'))
VOLATILE_SOURCE_SHA256 = 'b8f854640f7cedccb4cd0dddc4993b86259fafc52f0b2ca822d1a432561d90b1'
VOLATILE_BEFORE = '''                            mutatedVars.computeIfAbsent(tryCatch, k -> new IntHashSet())
                                    .add(definition.getVariableIndex());
                        } else {'''
VOLATILE_AFTER = '''                            mutatedVars.computeIfAbsent(tryCatch, k -> new IntHashSet())
                                    .add(definition.getVariableIndex());
                            for (var outerTryCatch : outerTryCatches) {
                                definitionsToBackupOnEntry.computeIfAbsent(outerTryCatch, k -> new IntHashSet())
                                        .add(definition.getVariableIndex());
                            }
                        } else {'''
PATCH_CLASSES = COROUTINE_CLASSES | TYPE_CLASSES | ASYNC_CLASSES | VOLATILE_CLASSES
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


def corrected_volatile_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != VOLATILE_SOURCE_SHA256:
        raise ValueError('unreviewed-teavm-volatile-definition-source')
    source = raw.decode('utf-8')
    if source.count(VOLATILE_BEFORE) != 1:
        raise ValueError('unreviewed-teavm-volatile-definition-preimage')
    source = source.replace(VOLATILE_BEFORE, VOLATILE_AFTER)
    for name in ('IntHashSet', 'IntSet'):
        before = 'import com.carrotsearch.hppc.' + name + ';'
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-volatile-definition-relocation')
        source = source.replace(before, 'import org.teavm.hppc.' + name + ';')
    return source.encode('utf-8')


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
                and name.endswith('.class')} != ASYNC_CLASSES
            or {name for name in result if name.startswith(VOLATILE_ROOT + 'VolatileDefinitionFinder')
                and name.endswith('.class')} != VOLATILE_CLASSES):
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
    volatile_raw = read_file(sdk / 'VolatileDefinitionFinder.java')
    volatile_source = folder / 'VolatileDefinitionFinder.java'
    corrected_volatile = corrected_volatile_source(volatile_raw); volatile_source.write_bytes(corrected_volatile)
    monitor_control = folder / 'MonitorAsyncControl.java'
    monitor_control.write_bytes(read_file(sdk / 'MonitorAsyncControl.java'))
    # Compiler.run provides the original process, output and remaining-time bounds.
    classes = folder / 'classes'
    read_file(sdk / 'Compile.java')
    compiler.run('java-coroutine-patch', 'java', sdk / 'Compile.java', source, control, classes,
                 os.pathsep.join(map(str, jars)), type_source, array_control, async_source, monitor_control,
                 volatile_source)
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
        upstreamVolatileDefinitionSourceSha256=VOLATILE_SOURCE_SHA256,
        correctedVolatileDefinitionSourceSha256=hashlib.sha256(corrected_volatile).hexdigest(),
        nestedHandlerReferenceBackupsPreserved=True,
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

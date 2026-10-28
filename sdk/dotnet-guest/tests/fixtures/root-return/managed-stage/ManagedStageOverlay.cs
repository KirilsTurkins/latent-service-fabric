using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

// Qualification-only post-derivation overlay. No default compiler selects it.
internal static class ManagedStageOverlay
{
    private const string Registry = "Lsf.CompilerOwned.ManagedWorkRuntime";
    private const string BaseSha = "bc449bac32313b547de63b4b852f1ff619ca91b22a24cc36f3526fa09df7e348";
    private const string CecilSha = "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7";
    private const int MaxAssembly = 8 * 1024 * 1024;
    private static readonly Dictionary<MethodDefinition, List<Instruction>> Added = new();
    private static readonly Dictionary<Instruction, object?> OldOperands = new();
    private static readonly List<MethodDefinition> NewMethods = new();
    private static readonly List<FieldDefinition> NewFields = new();
    private static readonly List<(ExceptionHandler Handler, Instruction? TryStart, Instruction? TryEnd,
        Instruction? HandlerStart, Instruction? HandlerEnd, Instruction? FilterStart)> OldHandlers = new();
    private static void Need(bool condition) { if (!condition) throw new InvalidDataException("managed-stage-preimage"); }
    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static byte[] Read(string path, int bound)
    {
        var info = new FileInfo(path);
        Need(info.Exists && info.LinkTarget is null && info.Length > 0 && info.Length <= bound);
        return File.ReadAllBytes(path);
    }
    // Display names can collide across distinct generic overloads. Preserve every method.
    private static string MethodKey(MethodDefinition method)
    {
        var ordinal = method.DeclaringType.Methods.IndexOf(method); Need(ordinal >= 0);
        return method.DeclaringType.FullName + "#" + ordinal.ToString(System.Globalization.CultureInfo.InvariantCulture);
    }
    private static string Body(MethodDefinition method)
    {
        if (!method.HasBody) return "no-body";
        var code = method.Body.Instructions.ToList();
        string At(Instruction? i) => i is null ? "end" : code.IndexOf(i) is int n && n >= 0
            ? n.ToString(System.Globalization.CultureInfo.InvariantCulture) : throw new InvalidDataException("managed-stage-branch");
        string Operand(object? value) => value switch {
            null => "none", Instruction i => "branch:" + At(i), Instruction[] a => "switch:" + string.Join(",", a.Select(At)),
            MethodReference m => "method:" + m.FullName, FieldReference f => "field:" + f.FullName,
            TypeReference t => "type:" + t.FullName, ParameterDefinition p => "parameter:" + p.Index,
            VariableDefinition v => "local:" + v.Index, string s => "string:" + s,
            CallSite c => "callsite:" + c.FullName,
            IFormattable n => value.GetType().FullName + ":" + n.ToString(null, System.Globalization.CultureInfo.InvariantCulture),
            _ => throw new InvalidDataException("managed-stage-operand") };
        return Hash(System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new {
            method.FullName, method.Attributes, method.ImplAttributes, method.CallingConvention, method.Body.InitLocals, method.Body.MaxStackSize,
            locals = method.Body.Variables.Select(v => v.VariableType.FullName).ToArray(),
            code = code.Select(i => new { op = i.OpCode.Code.ToString(), operand = Operand(i.Operand) }).ToArray(),
            handlers = method.Body.ExceptionHandlers.Select(h => new { kind = h.HandlerType.ToString(),
                start = At(h.TryStart), end = At(h.TryEnd), handler = At(h.HandlerStart), handlerEnd = At(h.HandlerEnd),
                filter = At(h.FilterStart), catchType = h.CatchType?.FullName }).ToArray() })));
    }
    private static void Insert(MethodDefinition method, Instruction target, bool before, params Instruction[] additions)
    {
        Need(method.HasBody && method.Body.Instructions.Contains(target) && additions.Length > 0);
        if (!Added.TryGetValue(method, out var added)) Added.Add(method, added = new());
        var il = method.Body.GetILProcessor();
        if (before)
        {
            foreach (var old in method.Body.Instructions.ToArray())
            {
                if (ReferenceEquals(old.Operand, target)) old.Operand = additions[0];
                else if (old.Operand is Instruction[] branches && branches.Contains(target))
                    old.Operand = branches.Select(i => ReferenceEquals(i, target) ? additions[0] : i).ToArray();
            }
            foreach (var h in method.Body.ExceptionHandlers)
            {
                if (ReferenceEquals(h.TryStart, target)) h.TryStart = additions[0];
                if (ReferenceEquals(h.TryEnd, target)) h.TryEnd = additions[0];
                if (ReferenceEquals(h.HandlerStart, target)) h.HandlerStart = additions[0];
                if (ReferenceEquals(h.HandlerEnd, target)) h.HandlerEnd = additions[0];
                if (ReferenceEquals(h.FilterStart, target)) h.FilterStart = additions[0];
            }
            foreach (var i in additions) il.InsertBefore(target, i);
        }
        else foreach (var i in additions) { il.InsertAfter(target, i); target = i; }
        added.AddRange(additions);
        method.Body.MaxStackSize += 4;
    }
    private static MethodDefinition New(TypeDefinition type, string name, TypeReference result, params TypeReference[] args)
    {
        Need(!type.Methods.Any(m => m.Name == name));
        var m = new MethodDefinition(name, MethodAttributes.Assembly | MethodAttributes.Static | MethodAttributes.HideBySig, result);
        foreach (var arg in args) m.Parameters.Add(new ParameterDefinition(arg));
        m.Body.MaxStackSize = 6; type.Methods.Add(m); NewMethods.Add(m); return m;
    }
    private static FieldDefinition Field(TypeDefinition type, string name, TypeReference value)
    {
        Need(!type.Fields.Any(f => f.Name == name));
        var f = new FieldDefinition(name, FieldAttributes.Private | FieldAttributes.Static, value);
        type.Fields.Add(f); NewFields.Add(f); return f;
    }
    private static Instruction[] Emit(MethodReference emit, Instruction owner, int stage, int guard = 0) =>
        new[] { owner, Instruction.Create(OpCodes.Ldc_I4, stage), Instruction.Create(OpCodes.Ldc_I4, guard), Instruction.Create(OpCodes.Call, emit) };
    private static Instruction Call(MethodDefinition m, string name) => m.Body.Instructions.Single(i =>
        i.Operand is MethodReference r && r.Name == name && r.DeclaringType.FullName == Registry);
    private static VariableDefinition Local(MethodDefinition m, TypeDefinition type) =>
        m.Body.Variables.Single(v => v.VariableType.FullName == type.FullName);
    private static void Guard(MethodDefinition m, string literal, MethodReference emit, int id)
    {
        var at = m.Body.Instructions.Single(i => i.OpCode == OpCodes.Ldstr && (string)i.Operand == literal);
        Need(at.Next.OpCode == OpCodes.Newobj && at.Next.Next.OpCode == OpCodes.Throw);
        Insert(m, at, true, Instruction.Create(OpCodes.Ldc_I4, id),
            Instruction.Create(OpCodes.Ldc_I4, id), Instruction.Create(OpCodes.Call, emit));
    }
    private static readonly Dictionary<Instruction, OpCode> OldOpcodes = new();
    private static int CheckShortBranches()
    {
        var count = 0; var enqueueCount = 0;
        foreach (var method in Added.Keys)
        {
            var offsets = new Dictionary<Instruction, int>(); var offset = 0;
            foreach (var instruction in method.Body.Instructions) { offsets.Add(instruction, offset); offset += instruction.GetSize(); }
            foreach (var instruction in method.Body.Instructions.Where(i => i.OpCode.OperandType == OperandType.ShortInlineBrTarget))
            {
                var displacement = offsets[(Instruction)instruction.Operand] - offsets[instruction] - instruction.GetSize();
                Need(displacement is >= -128 and <= 127);
                if (method.Name == "Enqueue") enqueueCount++; else count++;
            }
        }
        Need(count == 42 && enqueueCount == 24); return count + enqueueCount;
    }
    private static void Apply(ModuleDefinition module)
    {
        var types = module.GetTypes().ToDictionary(t => t.FullName);
        var registry = types[Registry]; var record = types[Registry + "/Record"];
        var task = types["System.Threading.Tasks.Task"]; var action = new GenericInstanceType(types["System.Action`2"]);
        action.GenericArguments.Add(module.TypeSystem.UInt32); action.GenericArguments.Add(module.TypeSystem.UInt32);
        var invoke = new MethodReference("Invoke", module.TypeSystem.Void, action) { HasThis = true };
        invoke.Parameters.Add(new ParameterDefinition(types["System.Action`2"].GenericParameters[0]));
        invoke.Parameters.Add(new ParameterDefinition(types["System.Action`2"].GenericParameters[1]));
        var callback = Field(registry, "stageCallback", action); var selected = Field(registry, "stageSelected", record); var selectedTask = Field(registry, "stageSelectedTask", task);
        FieldDefinition R(string name) => record.Fields.Single(f => f.Name == name);
        MethodDefinition M(string name) => registry.Methods.Single(m => m.Name == name);
        var emit = New(registry, "StageEmitSelected", module.TypeSystem.Void, record, module.TypeSystem.UInt32, module.TypeSystem.UInt32);
        var il = emit.Body.GetILProcessor(); var done = Instruction.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldsfld, registry.Fields.Single(f => f.Name == "installed")); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Brfalse, done); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldsfld, selected);
        il.Emit(OpCodes.Bne_Un, done);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldfld, R("Completion")); il.Emit(OpCodes.Ldsfld, selectedTask); il.Emit(OpCodes.Bne_Un, done);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Callvirt, invoke); il.Append(done);
        var emitGuard = New(registry, "StageEmitGuard", module.TypeSystem.Void, module.TypeSystem.UInt32, module.TypeSystem.UInt32);
        il = emitGuard.Body.GetILProcessor(); done = Instruction.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldsfld, registry.Fields.Single(f => f.Name == "installed")); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Callvirt, invoke); il.Append(done);
        var install = New(registry, "StageInstall", module.TypeSystem.Void, action); il = install.Body.GetILProcessor(); done = Instruction.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Brtrue, done); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Stsfld, callback); il.Append(done);
        var select = New(registry, "StageSelect", module.TypeSystem.Void, task); select.Body.InitLocals = true;
        var owner = new VariableDefinition(record); select.Body.Variables.Add(owner); il = select.Body.GetILProcessor(); done = Instruction.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldsfld, callback); il.Emit(OpCodes.Brfalse, done); il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Brtrue, done);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, M("Find")); il.Emit(OpCodes.Stloc, owner); il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Ldfld, R("Active")); il.Emit(OpCodes.Brfalse, done);
        foreach (var name in new[] { "Root", "Result" }) { il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Ldfld, R(name)); il.Emit(OpCodes.Brtrue, done); }
        il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Ldfld, R("Completion")); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Bne_Un, done);
        il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Ldfld, R("Outer")); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Callvirt, task.Methods.Single(m => m.Name == "get_IsCompleted")); il.Emit(OpCodes.Brtrue, done);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Stsfld, selectedTask);
        il.Emit(OpCodes.Ldloc, owner); il.Emit(OpCodes.Stsfld, selected);
        foreach (var i in Emit(emit, Instruction.Create(OpCodes.Ldloc, owner), 1)) il.Append(i); il.Append(done);
        foreach (var (name, target, parameters) in new[] {
            ("LsfManagedStageInstall", install, new TypeReference[] { action }),
            ("LsfManagedStageSelect", select, new TypeReference[] { task }) })
        {
            var forward = New(task, name, module.TypeSystem.Void, parameters); il = forward.Body.GetILProcessor();
            il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, target); il.Emit(OpCodes.Ret);
        }
        var inner = M("Inner"); var storeInner = inner.Body.Instructions.Single(i => i.OpCode == OpCodes.Stfld && i.Operand is FieldReference f && f.Name == "Inner");
        Insert(inner, storeInner, false, Emit(emit, Instruction.Create(OpCodes.Ldloc, Local(inner, record)), 2));
        var completed = M("Completed");
        Insert(completed, Call(completed, "HasRequired"), true, Emit(emit, Instruction.Create(OpCodes.Dup), 3));
        var finishCall = Call(completed, "Finish"); Insert(completed, finishCall, true, Emit(emit, Instruction.Create(OpCodes.Dup), 4));
        Insert(completed, finishCall, false, Emit(emit, Instruction.Create(OpCodes.Ldloc, Local(completed, record)), 9));
        var finish = M("Finish");
        var branch = finish.Body.Instructions.Single(i => i.Offset == 8);
        Need(branch.OpCode == OpCodes.Brfalse_S && branch.Operand is Instruction branchTarget && branchTarget.Offset == 81);
        OldOpcodes.Add(branch, branch.OpCode); branch.OpCode = OpCodes.Brfalse;
        var reserve = Call(finish, "Reserve");
        Insert(finish, reserve, true, Emit(emit, Instruction.Create(OpCodes.Dup), 5));
        Insert(finish, reserve, false, Emit(emit, Instruction.Create(OpCodes.Ldarg_0), 6));
        var settle = finish.Body.Instructions.Single(i => i.Operand is MethodReference r && r.Name == "Invoke" &&
            r.DeclaringType is GenericInstanceType g && g.ElementType.FullName == "System.Action`2");
        Insert(finish, settle, false, Emit(emit, Instruction.Create(OpCodes.Ldarg_0), 7));
        var result = finish.Body.Instructions.Single(i => i.OpCode == OpCodes.Stfld && i.Operand is FieldReference f && f.Name == "Result");
        Insert(finish, result, false, Emit(emit, Instruction.Create(OpCodes.Ldarg_0), 8));
        // Failure-only guards remain visible even when the actual failed owner is null/foreign.
        Guard(M("Enter"), "managed-work-execution-parent", emitGuard, 10);
        Guard(M("BindContext"), "managed-work-context-owner", emitGuard, 11);
        Guard(M("FreeRecord"), "managed-work-record-limit", emitGuard, 12);
        Guard(M("Release"), "managed-work-double-settle", emitGuard, 13);
        Guard(M("Release"), "managed-work-missing-record", emitGuard, 14);
        var parent = M("Parent");
        Guard(parent, "managed-work-parent-retired", emitGuard, 15);
        Guard(parent, "managed-work-independent-admission-closed", emitGuard, 16);
        Guard(M("Enqueue"), "managed-work-independent-admission-closed", emitGuard, 16);
        // Alias skip markers are emitted only when the original Completed guard will return.
        var alias = New(registry, "StageAliasSkip", module.TypeSystem.Void, task); il = alias.Body.GetILProcessor(); done = Instruction.Create(OpCodes.Ret);
        var outer = Instruction.Create(OpCodes.Ldsfld, selected); var emitOuter = Instruction.Create(OpCodes.Ldsfld, selected);
        var emitInner = Instruction.Create(OpCodes.Ldsfld, selected);
        il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Brfalse, done);
        il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Ldfld, R("Completion")); il.Emit(OpCodes.Ldsfld, selectedTask); il.Emit(OpCodes.Bne_Un, done);
        il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Ldfld, R("Completion")); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Beq, done);
        il.Append(outer); il.Emit(OpCodes.Ldfld, R("Outer")); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Beq, emitOuter);
        il.Emit(OpCodes.Ldsfld, selected); il.Emit(OpCodes.Ldfld, R("Inner")); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Beq, emitInner); il.Emit(OpCodes.Br, done);
        foreach (var i in Emit(emit, emitOuter, 17)) il.Append(i); il.Emit(OpCodes.Br, done);
        foreach (var i in Emit(emit, emitInner, 18)) il.Append(i); il.Append(done);
        Insert(completed, completed.Body.Instructions[0], true, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, alias));
    }
    private static int Main(string[] args)
    {
        Need(args.Length == 3 && args.Distinct(StringComparer.Ordinal).Count() == 3);
        Need(Hash(Read(args[0], MaxAssembly)) == BaseSha && Hash(Read(typeof(ModuleDefinition).Assembly.Location, 512 * 1024)) == CecilSha);
        Need(!File.Exists(args[1]) && !Directory.Exists(args[1]) && !File.Exists(args[2]) && !Directory.Exists(args[2]));
        using var module = ModuleDefinition.ReadModule(args[0], new ReaderParameters { ReadWrite = false, ReadSymbols = false });
        Need(module.Assembly.Name.FullName == "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e");
        var methods = module.GetTypes().SelectMany(t => t.Methods).ToArray();
        Need(methods.Length is >= 10000 and <= 65536);
        var oldMaxStack = methods.Where(m => m.HasBody).ToDictionary(m => m, m => m.Body.MaxStackSize);
        var before = methods.ToDictionary(m => m, Body); var references = module.AssemblyReferences.Select(r => r.FullName).ToArray();
        foreach (var m in methods.Where(m => m.HasBody))
        {
            foreach (var i in m.Body.Instructions) OldOperands.Add(i, i.Operand is Instruction[] a ? a.ToArray() : i.Operand);
            foreach (var h in m.Body.ExceptionHandlers) OldHandlers.Add((h, h.TryStart, h.TryEnd, h.HandlerStart, h.HandlerEnd, h.FilterStart));
        }
        var fields = module.GetTypes().SelectMany(t => t.Fields).Select(f => (f.FullName, f.Attributes, f.Constant)).ToArray();
        Apply(module);
        Need(references.SequenceEqual(module.AssemblyReferences.Select(r => r.FullName)));
        var changed = methods.Where(m => Body(m) != before[m]).ToDictionary(m => m.FullName,
            m => new { before = before[m], after = Body(m), insertedInstructions = Added[m].Count });
        Need(changed.Count == 9 && NewMethods.Count == 7 && NewFields.Count == 3);
        var shortBranchesChecked = CheckShortBranches();
        module.Write(args[1]); var selectedHash = Hash(Read(args[1], MaxAssembly));
        // Bind the ACTUAL serialized image, including writer-computed MaxStack.
        using var written = ModuleDefinition.ReadModule(args[1], new ReaderParameters { ReadWrite = false, ReadSymbols = false });
        var plannedTypes = module.GetTypes().ToArray(); var writtenTypes = written.GetTypes().ToArray();
        Need(plannedTypes.Select(t => t.FullName).SequenceEqual(writtenTypes.Select(t => t.FullName)));
        foreach (var pair in plannedTypes.Zip(writtenTypes))
            Need(pair.First.Methods.Select(m => m.FullName).SequenceEqual(pair.Second.Methods.Select(m => m.FullName)));
        var writtenMethods = writtenTypes.SelectMany(t => t.Methods).ToDictionary(MethodKey);
        var plannedMethods = module.GetTypes().SelectMany(t => t.Methods).ToArray();
        var finishName = MethodKey(methods.Single(m => m.Name == "Finish" && m.DeclaringType.FullName == Registry));
        var selectedFinishBytes = writtenMethods[finishName].Body.CodeSize; Need(selectedFinishBytes == 155);
        Need(writtenMethods.Count == plannedMethods.Length && references.SequenceEqual(written.AssemblyReferences.Select(r => r.FullName)));
        var actualBodies = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var planned in plannedMethods)
        {
            Need(writtenMethods.TryGetValue(MethodKey(planned), out var actual));
            var actualBody = Body(actual!); actualBodies.Add(MethodKey(planned), actualBody);
            if (actual!.HasBody)
            {
                var serializedMaxStack = actual.Body.MaxStackSize;
                actual.Body.MaxStackSize = planned.Body.MaxStackSize;
                Need(Body(actual) == Body(planned));
                actual.Body.MaxStackSize = serializedMaxStack;
            }
            else Need(actualBody == Body(planned));
        }
        Need(module.GetTypes().SelectMany(t => t.Fields).Select(f => (f.FullName, f.Attributes, f.Constant))
            .SequenceEqual(written.GetTypes().SelectMany(t => t.Fields).Select(f => (f.FullName, f.Attributes, f.Constant))));
        var actualChanged = methods.Where(m => changed.ContainsKey(m.FullName)).ToDictionary(m => m.FullName,
            m => new { before = before[m], after = actualBodies[MethodKey(m)], insertedInstructions = Added[m].Count,
                serializedMaxStack = writtenMethods[MethodKey(m)].Body.MaxStackSize });
        Need(methods.Where(m => !changed.ContainsKey(m.FullName)).All(m => actualBodies[MethodKey(m)] == before[m]));
        var actualBodySetDigest = Hash(System.Text.Encoding.UTF8.GetBytes(string.Join("\n", actualBodies.Select(p => p.Key + "=" + p.Value))));
        foreach (var pair in Added) foreach (var i in pair.Value) pair.Key.Body.Instructions.Remove(i);
        foreach (var pair in OldOperands) pair.Key.Operand = pair.Value;
        foreach (var pair in OldOpcodes) pair.Key.OpCode = pair.Value;
        foreach (var pair in oldMaxStack) pair.Key.Body.MaxStackSize = pair.Value;
        foreach (var h in OldHandlers) { h.Handler.TryStart = h.TryStart; h.Handler.TryEnd = h.TryEnd; h.Handler.HandlerStart = h.HandlerStart;
            h.Handler.HandlerEnd = h.HandlerEnd; h.Handler.FilterStart = h.FilterStart; }
        foreach (var m in NewMethods) m.DeclaringType.Methods.Remove(m);
        foreach (var f in NewFields) f.DeclaringType.Fields.Remove(f);
        Need(methods.All(m => Body(m) == before[m]) && fields.SequenceEqual(module.GetTypes().SelectMany(t => t.Fields).Select(f => (f.FullName, f.Attributes, f.Constant))));
        Need(references.SequenceEqual(module.AssemblyReferences.Select(r => r.FullName)));
        var receipt = JsonSerializer.SerializeToUtf8Bytes(new { profile = "dotnet-managed-stage-diagnostic-v2",
            originalDigest = "sha256:" + BaseSha, outputDigest = "sha256:" + selectedHash, cecilDigest = "sha256:" + CecilSha,
            modifiedMethods = actualChanged, actualSerializedBodySetDigest = "sha256:" + actualBodySetDigest,
            actualSerializedMethods = actualBodies.Count, actualWrittenBodiesVerified = true, originalMethodCount = methods.Length, originalInstructionsAndHandlersInverseExact = true,
            branchNormalization = new { method = "Finish", originalOffset = 8, originalTargetOffset = 81,
                originalOpcode = "brfalse.s", selectedOpcode = "brfalse", selectedMethodBytes = selectedFinishBytes,
                shortBranchesChecked, originalOpcodeRestoredByInverse = true },
            newFields = 3, newMethods = 7, newAssemblyReferences = 0, maxEvents = 16, diagnosticOnly = true,
            originalFaultQualified = false, physicalRetirementQualified = false, fullAC7Qualified = false });
        Need(receipt.Length <= 64 * 1024);
        using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None); output.Write(receipt); return 0;
    }
}
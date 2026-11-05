using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;

// Selected managed-finite derivation; host-reference projections live separately.
// Keep the original countdown, task listeners, exceptions and detach finally.
internal static class AggregateTaskWait
{
    private const string Prefix = "LsfAggregate";
    private static readonly (int Token, int Bytes, string Sha256)[] Originals = [
        (0x06003e7f, 46, "87d5707683590051481de68a5c41d27654e0223f72d9d826950aa6bded0015fa"),
        (0x06003e80, 31, "3230751c809caea2191f78d05b867d24c6d54fc334e66ab2aae202af25d09355"),
        (0x06003e81, 85, "01319d2a08ba4ae07b1e5c364d0b4fd338471aa848c34777c235a4e90c5b571e"),
        (0x06003e82, 45, "5968cd2411bfc34c2ecd8ef2211d03618cfbfe40c12ff05d72b6e8f8f45524b0"),
        (0x06003e83, 38, "dce230be52341bd676be3317c7898112d7795f4570f647eef7a2e4b4a50a4935"),
        (0x06003e84, 37, "6343973682f40d3769ee6c682104d4cb968b473be63720a76cf5bd24511220c0"),
        (0x06003e85, 84, "4964812ad96bbf22498f0b6aa72665266aab885ac8281a13244699fdcd49201a"),
        (0x06003e86, 471, "244c14ca727b59a6291824b90984aa76c49bf5e091cf8bc00a8e10a187f4bb6d"),
        (0x06003e88, 149, "2b0fb5a58f02b0341e2b94dbcb1460307e1e7b256f994f4b0956bfcfa1bb6d00"),
    ];

    private static void Need(bool value)
    {
        if (!value) throw new InvalidDataException("aggregate-task-wait-preimage-or-shape");
    }

    private static void Raw(PEReader reader, MethodDefinition method, int bytes, string sha256)
    {
        var raw = System.Reflection.Metadata.PEReaderExtensions.GetMethodBody(reader, checked((int)method.RVA)).GetILBytes();
        Need(raw is not null && raw.Length == bytes
            && Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant() == sha256);
    }

    private static MethodDefinition New(TypeDefinition owner, string name, TypeReference result,
        MethodAttributes attributes, params TypeReference[] parameters)
    {
        Need(!owner.Methods.Any(method => method.Name == name));
        var method = new MethodDefinition(name, attributes | MethodAttributes.HideBySig, result);
        method.HasThis = (attributes & MethodAttributes.Static) == 0;
        foreach (var parameter in parameters) method.Parameters.Add(new ParameterDefinition(parameter));
        method.Body.InitLocals = true; method.Body.MaxStackSize = 8;
        owner.Methods.Add(method);
        return method;
    }

    // Redirect every original entry to a replaced sequence, including EH edges.
    private static void Retarget(MethodDefinition method, Instruction original, Instruction replacement)
    {
        foreach (var instruction in method.Body.Instructions)
        {
            if (ReferenceEquals(instruction.Operand, original)) instruction.Operand = replacement;
            else if (instruction.Operand is Instruction[] branches)
                for (int i = 0; i < branches.Length; i++)
                    if (ReferenceEquals(branches[i], original)) branches[i] = replacement;
        }
        foreach (var handler in method.Body.ExceptionHandlers)
        {
            if (handler.TryStart == original) handler.TryStart = replacement;
            if (handler.TryEnd == original) handler.TryEnd = replacement;
            if (handler.HandlerStart == original) handler.HandlerStart = replacement;
            if (handler.HandlerEnd == original) handler.HandlerEnd = replacement;
            if (handler.FilterStart == original) handler.FilterStart = replacement;
        }
    }

    private static void RemoveGuard(MethodDefinition method)
    {
        var old = method.Body.Instructions.Take(4).ToArray();
        var body = old[3].Next;
        Need(old[0].OpCode == OpCodes.Call && old[0].Operand is MethodReference wasi
            && wasi.FullName == "System.Boolean System.OperatingSystem::IsWasi()"
            && old[1].OpCode == OpCodes.Brfalse_S && old[1].Operand == body
            && old[2].OpCode == OpCodes.Newobj && old[2].Operand is MethodReference constructor
            && constructor.FullName == "System.Void System.PlatformNotSupportedException::.ctor()"
            && old[3].OpCode == OpCodes.Throw && body is not null);
        Need(!method.Body.Instructions.Skip(4).Any(instruction =>
            instruction.Operand is Instruction branch && old.Contains(branch)
            || instruction.Operand is Instruction[] branches && branches.Any(old.Contains)));
        Need(!method.Body.ExceptionHandlers.Any(handler => old.Contains(handler.TryStart)
            || old.Contains(handler.TryEnd) || old.Contains(handler.HandlerStart)
            || old.Contains(handler.HandlerEnd) || old.Contains(handler.FilterStart)));
        foreach (var instruction in old) method.Body.Instructions.Remove(instruction);
    }

    private static (MethodDefinition Method, string Original) DetachTimerPumpBatch(ModuleDefinition module, PEReader reader)
    {
        var queue = module.GetTypes().Single(type => type.FullName == "System.Threading.TimerQueue");
        var pump = queue.Methods.Single(method => method.Name == "PumpTimerQueue");
        var set = queue.Methods.Single(method => method.Name == "SetTimer");
        Need(pump.MetadataToken.ToInt32() == 0x06003c90 && pump.IsStatic
            && pump.ReturnType.MetadataType == MetadataType.Int64 && pump.Parameters.Count == 1
            && pump.Parameters[0].ParameterType.MetadataType == MetadataType.Int64
            && set.MetadataToken.ToInt32() == 0x06003c8d);
        Raw(reader, pump, 214, "e486da68fcceeed848c7b35adbf5956f7345b9e3e63a05553148b83d2d7ba44b");
        Raw(reader, set, 103, "b1cd9f5485b97d9954a55a73c7a11da54e532c577300ab3e213b89dc11f2e30e");
        var batch = queue.Fields.Single(field => field.Name == "s_scheduledTimersToFire");
        Need(batch.IsStatic && batch.MetadataToken.ToInt32() == 0x04000c56
            && batch.FieldType is GenericInstanceType list
            && list.ElementType.FullName == "System.Collections.Generic.List`1"
            && list.GenericArguments.Count == 1 && list.GenericArguments[0].FullName == queue.FullName);
        var instances = queue.Methods.Single(method => method.Name == "get_Instances" && method.IsStatic
            && method.Parameters.Count == 0 && method.ReturnType is ArrayType array
            && array.ElementType.FullName == queue.FullName);
        var constructors = set.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Newobj
            && instruction.Operand is MethodReference method && method.DeclaringType.FullName == batch.FieldType.FullName)
            .Select(instruction => (MethodReference)instruction.Operand).ToArray();
        Need(constructors.Length == 2 && constructors.Select(method => method.FullName).Distinct().Count() == 1);
        var constructor = constructors[0];
        Need(constructor.Name == ".ctor" && constructor.HasThis && constructor.Parameters.Count == 1
            && constructor.Parameters[0].ParameterType.MetadataType == MetadataType.Int32
            && constructor.ReturnType.MetadataType == MetadataType.Void);
        var get = pump.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Callvirt
            && instruction.Operand is MethodReference method && method.Name == "GetEnumerator"
            && method.DeclaringType.FullName == batch.FieldType.FullName);
        var anchor = get.Previous;
        Need(anchor.OpCode == OpCodes.Ldloc_0 && anchor.Previous.OpCode == OpCodes.Ble_S
            && pump.Body.Variables.Count == 7 && pump.Body.Variables[0].VariableType.FullName == batch.FieldType.FullName
            && pump.Body.ExceptionHandlers.Count == 1
            && pump.Body.ExceptionHandlers[0].HandlerType == ExceptionHandlerType.Finally
            && anchor.Offset < pump.Body.ExceptionHandlers[0].TryStart.Offset
            && !pump.Body.Instructions.Any(instruction => instruction.Operand == anchor
                || instruction.Operand is Instruction[] branches && branches.Contains(anchor)));
        var original = TaskWait.BodyIdentity(pump);
        var il = pump.Body.GetILProcessor();
        il.InsertBefore(anchor, Instruction.Create(OpCodes.Call, instances));
        il.InsertBefore(anchor, Instruction.Create(OpCodes.Ldlen));
        il.InsertBefore(anchor, Instruction.Create(OpCodes.Conv_I4));
        il.InsertBefore(anchor, Instruction.Create(OpCodes.Newobj, constructor));
        il.InsertBefore(anchor, Instruction.Create(OpCodes.Stsfld, batch));
        VerifyTimerPump(module, original);
        return (pump, original);
    }

    internal static void VerifyTimerPump(ModuleDefinition module, string original)
    {
        var queue = module.GetTypes().Single(type => type.FullName == "System.Threading.TimerQueue");
        var pump = queue.Methods.Single(method => method.Name == "PumpTimerQueue");
        var get = pump.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Callvirt
            && instruction.Operand is MethodReference method && method.Name == "GetEnumerator");
        var anchor = get.Previous;
        var inserted = new Instruction[5];
        var cursor = anchor.Previous;
        for (int i = 4; i >= 0; i--) { inserted[i] = cursor; cursor = cursor.Previous; }
        Need(anchor.OpCode == OpCodes.Ldloc_0 && cursor.OpCode == OpCodes.Ble_S
            && inserted[0].OpCode == OpCodes.Call && inserted[0].Operand is MethodReference instances
            && instances.FullName == "System.Threading.TimerQueue[] System.Threading.TimerQueue::get_Instances()"
            && inserted[1].OpCode == OpCodes.Ldlen && inserted[2].OpCode == OpCodes.Conv_I4
            && inserted[3].OpCode == OpCodes.Newobj && inserted[3].Operand is MethodReference constructor
            && constructor.FullName == "System.Void System.Collections.Generic.List`1<System.Threading.TimerQueue>::.ctor(System.Int32)"
            && inserted[4].OpCode == OpCodes.Stsfld && inserted[4].Operand is FieldReference field
            && field.Name == "s_scheduledTimersToFire" && field.DeclaringType.FullName == queue.FullName);
        Need(!pump.Body.Instructions.Except(inserted).Any(instruction => instruction.Operand is Instruction branch && inserted.Contains(branch)
            || instruction.Operand is Instruction[] branches && branches.Any(inserted.Contains))
            && !pump.Body.ExceptionHandlers.Any(handler => inserted.Contains(handler.TryStart) || inserted.Contains(handler.TryEnd)
                || inserted.Contains(handler.HandlerStart) || inserted.Contains(handler.HandlerEnd) || inserted.Contains(handler.FilterStart)));
        var selected = TaskWait.BodyIdentity(pump);
        var il = pump.Body.GetILProcessor();
        foreach (var instruction in inserted) il.Remove(instruction);
        try { Need(TaskWait.BodyIdentity(pump) == original); }
        finally { foreach (var instruction in inserted) il.InsertBefore(anchor, instruction); }
        Need(TaskWait.BodyIdentity(pump) == selected);
    }

    internal static (MethodDefinition[] Changed, object Receipt, Dictionary<string, string> Remainders, string TimerPumpOriginal) Install(ModuleDefinition module, PEReader reader)
    {
        TypeDefinition Type(string name) => module.GetTypes().Single(type => type.FullName == name);
        var task = Type("System.Threading.Tasks.Task");
        var loop = Type("System.Threading.WasiEventLoop");
        var mres = Type("System.Threading.ManualResetEventSlim");
        var token = Type("System.Threading.CancellationToken");
        var cts = Type("System.Threading.CancellationTokenSource");
        var context = Type("System.Threading.ExecutionContext");
        var callback = Type("System.Threading.ContextCallback");
        var members = Originals.Select(row => (MethodDefinition)module.LookupToken(row.Token)).ToArray();
        Need(task.Methods.Count(method => method.Name == "WaitAll") == 7
            && members.Count(method => method.Name == "WaitAll") == 7
            && members.All(method => method.DeclaringType == task && method.IsStatic)
            && members[^2].Name == "WaitAllCore" && members[^1].Name == "WaitAllBlockingCore");
        for (int i = 0; i < members.Length; i++) Raw(reader, members[i], Originals[i].Bytes, Originals[i].Sha256);
        var remainders = members.ToDictionary(method => method.FullName, method => TaskWait.BodyIdentity(method, 4));
        var check = loop.Methods.Single(method => method.Name == "CheckPollables");
        var dispatch = Type("System.Threading.ThreadPoolWorkQueue").Methods.Single(method => method.Name == "Dispatch");
        var originalLoop = loop.Methods.Single(method => method.Name == "PollWasiEventLoopUntilResolvedVoid");
        Raw(reader, dispatch, 556, "05e0128b899121d13842a4c76993d2becaaebe2e57ecff53f1ea750ba39ba629");
        Raw(reader, originalLoop, 44, "1631857d71d2e5ecca2e22c95a6421aaecf016d9cba018412388b2d1c6646e19");
        Raw(reader, check, 546, "ae0bff31c6a3187f9dc4504113179434fb589ab402124d9350a5faec1ef98a62");

        var isSet = mres.Methods.Single(method => method.Name == "get_IsSet");
        var wait = mres.Methods.Single(method => method.Name == "Wait" && method.Parameters.Count == 2
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.Int32);
        Raw(reader, wait, 363, "352b3e91a4ef4bbca4d85c64f0d534c3f2606f1ac63e6eb0c7a1af73cc6761fb");
        var tick = Type("System.Environment").Methods.Single(method => method.Name == "get_TickCount64");
        var remaining = Type("System.Threading.TimeoutHelper").Methods.Single(method => method.Name == "UpdateTimeOut");
        Raw(reader, tick, 6, "1963fc8ceb84b61703ea6156ed3d91cbedb480b0c0348697243943e73896cadd");
        Raw(reader, remaining, 37, "f3834985458c4d55a958c241f5bc3e6c4196473162b11e9b3a749a48213dc6d4");
        Need(isSet.IsPublic && !isSet.IsStatic && isSet.ReturnType.MetadataType == MetadataType.Boolean
            && tick.IsPublic && tick.IsStatic && remaining.IsStatic
            && remaining.Parameters.Count == 2 && remaining.Parameters.All(p => p.ParameterType.MetadataType == MetadataType.Int64));
        var throwCancelled = token.Methods.Single(method => method.Name == "ThrowIfCancellationRequested");
        var cancelled = token.Methods.Single(method => method.Name == "get_IsCancellationRequested");
        var canCancel = token.Methods.Single(method => method.Name == "get_CanBeCanceled");
        var linked = cts.Methods.Single(method => method.Name == "CreateLinkedTokenSource" && method.Parameters.Count == 1
            && method.Parameters[0].ParameterType.FullName == token.FullName);
        var ownToken = cts.Methods.Single(method => method.Name == "get_Token");
        var cancel = cts.Methods.Single(method => method.Name == "Cancel" && method.Parameters.Count == 0);
        var dispose = cts.Methods.Single(method => method.Name == "Dispose" && method.Parameters.Count == 0);
        var delay = task.Methods.Single(method => method.Name == "Delay" && method.Parameters.Count == 2
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.Int32
            && method.Parameters[1].ParameterType.FullName == token.FullName);
        var current = loop.Fields.Single(field => field.Name == "s_mainTask");
        var depth = loop.Fields.Single(field => field.Name == "s_lsfTaskWaitDepth");
        var single = loop.Methods.Single(method => method.Name == "LsfWaitForActualTaskCompletion");
        var ensureReady = Type("Lsf.CompilerOwned.ManagedWorkRuntime").Methods.Single(method => method.Name == "EnsureJoinReady");
        Need(current.IsStatic && current.FieldType.FullName == task.FullName && depth.IsStatic
            && !loop.Fields.Any(field => field.Name.StartsWith("s_lsfAggregate", StringComparison.Ordinal)));
        var target = new FieldDefinition("s_lsfAggregateTarget", FieldAttributes.Private | FieldAttributes.Static, mres);
        var callerToken = new FieldDefinition("s_lsfAggregateToken", FieldAttributes.Private | FieldAttributes.Static, token);
        var start = new FieldDefinition("s_lsfAggregateStart", FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Int64);
        var timeout = new FieldDefinition("s_lsfAggregateTimeout", FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Int32);
        var observedCompletion = new FieldDefinition("s_lsfAggregateCompleted", FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Boolean);
        foreach (var field in new[] { target, callerToken, start, timeout, observedCompletion }) loop.Fields.Add(field);

        var ready = New(loop, Prefix + "Ready", module.TypeSystem.Boolean,
            MethodAttributes.Private | MethodAttributes.Static);
        var il = ready.Body.GetILProcessor();
        var legacy = Instruction.Create(OpCodes.Ldsfld, current);
        var yes = Instruction.Create(OpCodes.Ldc_I4_1); var no = Instruction.Create(OpCodes.Ldc_I4_0);
        il.Emit(OpCodes.Ldsfld, target); il.Emit(OpCodes.Brfalse, legacy);
        il.Emit(OpCodes.Ldsfld, target); il.Emit(OpCodes.Callvirt, isSet); il.Emit(OpCodes.Brtrue, yes);
        il.Emit(OpCodes.Ldsflda, callerToken); il.Emit(OpCodes.Call, cancelled); il.Emit(OpCodes.Brtrue, yes);
        il.Emit(OpCodes.Ldsfld, timeout); il.Emit(OpCodes.Ldc_I4_M1); il.Emit(OpCodes.Beq, no);
        il.Emit(OpCodes.Ldsfld, start); il.Emit(OpCodes.Ldsfld, timeout); il.Emit(OpCodes.Conv_I8);
        il.Emit(OpCodes.Call, remaining); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Ble, yes);
        il.Emit(OpCodes.Br, no);
        il.Append(legacy); il.Emit(OpCodes.Brfalse, no); il.Emit(OpCodes.Ldsfld, current);
        il.Emit(OpCodes.Callvirt, task.Methods.Single(method => method.Name == "get_IsCompleted")); il.Emit(OpCodes.Ret);
        il.Append(yes); il.Emit(OpCodes.Ret); il.Append(no); il.Emit(OpCodes.Ret);

        // Replace only the original five-instruction main-target condition.
        var sites = check.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ldsfld
            && instruction.Operand is FieldReference field && field.FullName == current.FullName).ToArray();
        Need(sites.Length == 2 && sites[0].Next.Next == sites[1]
            && sites[0].Next.OpCode.FlowControl == FlowControl.Cond_Branch
            && sites[1].Next.OpCode == OpCodes.Callvirt
            && sites[1].Next.Operand is MethodReference completed && completed.FullName == "System.Boolean System.Threading.Tasks.Task::get_IsCompleted()"
            && sites[1].Next.Next.OpCode.FlowControl == FlowControl.Cond_Branch
            && sites[0].Next.Operand == sites[1].Next.Next.Operand);
        var removed = new[] { sites[0], sites[0].Next, sites[1], sites[1].Next, sites[1].Next.Next };
        Need(removed[1].OpCode.Code is Code.Brfalse or Code.Brfalse_S
            && removed[4].OpCode.Code is Code.Brfalse or Code.Brfalse_S);
        Need(!check.Body.Instructions.Except(removed).Any(instruction =>
            instruction.Operand is Instruction branch && removed.Skip(1).Contains(branch)
            || instruction.Operand is Instruction[] branches && branches.Any(removed.Skip(1).Contains)));
        var replacement = Instruction.Create(OpCodes.Call, ready);
        var code = check.Body.GetILProcessor();
        code.InsertBefore(removed[0], replacement);
        code.InsertBefore(removed[0], Instruction.Create(OpCodes.Brfalse, (Instruction)removed[1].Operand));
        Retarget(check, removed[0], replacement);
        foreach (var instruction in removed) code.Remove(instruction);

        // Nested single waits mask only the aggregate target and restore it in
        // the existing main-task/depth finally. The other four fields are idle
        // while masked; nested aggregates save/restore all five independently.
        var previousTarget = new VariableDefinition(mres); single.Body.Variables.Add(previousTarget);
        var savedMain = single.Body.Variables.Single(variable => variable.VariableType.FullName == task.FullName);
        var save = single.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Stloc && instruction.Operand == savedMain);
        code = single.Body.GetILProcessor();
        var loadTarget = Instruction.Create(OpCodes.Ldsfld, target);
        code.InsertAfter(save, loadTarget); code.InsertAfter(loadTarget, Instruction.Create(OpCodes.Stloc, previousTarget));
        var outerFinally = single.Body.ExceptionHandlers.Single(handler => handler.HandlerType == ExceptionHandlerType.Finally);
        var clearTarget = Instruction.Create(OpCodes.Ldnull);
        code.InsertBefore(outerFinally.TryStart, clearTarget);
        code.InsertBefore(outerFinally.TryStart, Instruction.Create(OpCodes.Stsfld, target));
        Retarget(single, outerFinally.TryStart, clearTarget);
        var restoreMain = outerFinally.HandlerStart.Next;
        Need(restoreMain.OpCode == OpCodes.Stsfld && restoreMain.Operand == current);
        var restoreTarget = Instruction.Create(OpCodes.Ldloc, previousTarget);
        code.InsertAfter(restoreMain, restoreTarget); code.InsertAfter(restoreTarget, Instruction.Create(OpCodes.Stsfld, target));

        var body = New(loop, Prefix + "Dispatch", module.TypeSystem.Void,
            MethodAttributes.Private | MethodAttributes.Static, module.TypeSystem.Object);
        il = body.Body.GetILProcessor();
        var again = Instruction.Create(OpCodes.Ldsfld, target); var done = Instruction.Create(OpCodes.Ret);
        var completedAggregate = Instruction.Create(OpCodes.Ldc_I4_1);
        il.Append(again); il.Emit(OpCodes.Callvirt, isSet); il.Emit(OpCodes.Brtrue, completedAggregate);
        il.Emit(OpCodes.Ldsflda, callerToken); il.Emit(OpCodes.Call, throwCancelled);
        var dispatchNext = Instruction.Create(OpCodes.Call, ensureReady);
        il.Emit(OpCodes.Ldsfld, timeout); il.Emit(OpCodes.Ldc_I4_M1); il.Emit(OpCodes.Beq, dispatchNext);
        il.Emit(OpCodes.Ldsfld, start); il.Emit(OpCodes.Ldsfld, timeout); il.Emit(OpCodes.Conv_I8);
        il.Emit(OpCodes.Call, remaining); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Ble, done);
        il.Append(dispatchNext); il.Emit(OpCodes.Call, dispatch); il.Emit(OpCodes.Pop); il.Emit(OpCodes.Br, again);
        il.Append(completedAggregate); il.Emit(OpCodes.Stsfld, observedCompletion); il.Append(done);

        var entry = New(loop, Prefix + "Wait", module.TypeSystem.Boolean,
            MethodAttributes.Assembly | MethodAttributes.Static, mres, module.TypeSystem.Int32, token);
        var oldTarget = new VariableDefinition(mres); var oldToken = new VariableDefinition(token);
        var oldStart = new VariableDefinition(module.TypeSystem.Int64); var oldTimeout = new VariableDefinition(module.TypeSystem.Int32);
        var oldMain = new VariableDefinition(task); var source = new VariableDefinition(cts);
        var oldCompletion = new VariableDefinition(module.TypeSystem.Boolean);
        var result = new VariableDefinition(module.TypeSystem.Boolean); var wake = new VariableDefinition(task);
        foreach (var variable in new[] { oldTarget, oldToken, oldStart, oldTimeout, oldMain, oldCompletion, source, result, wake }) entry.Body.Variables.Add(variable);
        il = entry.Body.GetILProcessor();
        var incomplete = Instruction.Create(OpCodes.Ldarg_1); var nonzero = Instruction.Create(OpCodes.Ldsfld, depth);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Callvirt, isSet); il.Emit(OpCodes.Brfalse, incomplete);
        il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Ret); il.Append(incomplete); il.Emit(OpCodes.Brtrue, nonzero);
        il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Ret); il.Append(nonzero); il.Emit(OpCodes.Ldc_I4, 32);
        var admit = Instruction.Create(OpCodes.Ldsfld, target);
        il.Emit(OpCodes.Blt, admit); il.Emit(OpCodes.Ldstr, "activation-task-wait-depth-limit");
        il.Emit(OpCodes.Newobj, Type("System.InvalidOperationException").Methods.Single(method => method.IsConstructor
            && method.Parameters.Count == 1 && method.Parameters[0].ParameterType.MetadataType == MetadataType.String)); il.Emit(OpCodes.Throw);
        il.Append(admit); il.Emit(OpCodes.Stloc, oldTarget);
        foreach (var pair in new[] { (callerToken, oldToken), (start, oldStart), (timeout, oldTimeout), (current, oldMain), (observedCompletion, oldCompletion) })
        { il.Emit(OpCodes.Ldsfld, pair.Item1); il.Emit(OpCodes.Stloc, pair.Item2); }
        // Mutations start inside the finally-protected region. No aggregate
        // object or owner is forgotten if linked-source/timer admission fails.
        var install = Instruction.Create(OpCodes.Ldsfld, depth);
        il.Append(install); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Add); il.Emit(OpCodes.Stsfld, depth);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Stsfld, target);
        il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Stsfld, callerToken);
        // An infinite wait performs no clock read, just as original MRES.Wait.
        // Only finite waits capture the one original monotonic interval.
        var haveStart = Instruction.Create(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Stsfld, start);
        il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldc_I4_M1); il.Emit(OpCodes.Beq, haveStart);
        il.Emit(OpCodes.Call, tick); il.Emit(OpCodes.Stsfld, start);
        il.Append(haveStart); il.Emit(OpCodes.Stsfld, timeout);
        il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Stsfld, observedCompletion);
        var run = Instruction.Create(OpCodes.Ldsfld, context.Fields.Single(field => field.Name == "Default"));
        var makeWake = Instruction.Create(OpCodes.Ldarg_2);
        il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldc_I4_M1); il.Emit(OpCodes.Bne_Un, makeWake);
        il.Emit(OpCodes.Ldarga, entry.Parameters[2]); il.Emit(OpCodes.Call, canCancel); il.Emit(OpCodes.Brfalse, run);
        il.Append(makeWake); il.Emit(OpCodes.Call, linked); il.Emit(OpCodes.Stloc, source);
        var infiniteWake = Instruction.Create(OpCodes.Ldc_I4_M1); var haveDuration = Instruction.Create(OpCodes.Ldloc, source);
        il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldc_I4_M1); il.Emit(OpCodes.Beq, infiniteWake);
        il.Emit(OpCodes.Ldsfld, start); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Call, remaining); il.Emit(OpCodes.Conv_I4);
        il.Emit(OpCodes.Br, haveDuration); il.Append(infiniteWake); il.Append(haveDuration);
        il.Emit(OpCodes.Callvirt, ownToken); il.Emit(OpCodes.Call, delay); il.Emit(OpCodes.Stloc, wake);
        il.Append(run); il.Emit(OpCodes.Ldnull); il.Emit(OpCodes.Ldftn, body);
        il.Emit(OpCodes.Newobj, callback.Methods.Single(method => method.IsConstructor && method.Parameters.Count == 2));
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, context.Methods.Single(method => method.Name == "RunInternal"));
        // RunInternal restoration may invoke original AsyncLocal notifications.
        // Capture the body's decision, never re-query MRES after those callbacks.
        il.Emit(OpCodes.Ldsfld, observedCompletion); il.Emit(OpCodes.Stloc, result);
        var returnResult = Instruction.Create(OpCodes.Ldloc, result);
        il.Emit(OpCodes.Leave, returnResult);
        var cancelSource = Instruction.Create(OpCodes.Ldloc, source);
        var disposeSource = Instruction.Create(OpCodes.Ldloc, source);
        var afterSource = Instruction.Create(OpCodes.Nop);
        var restore = Instruction.Create(OpCodes.Ldloc, oldTarget);
        // A separate outer finally restores the wait target even if the private
        // source's original Cancel or Dispose refuses/traps.
        il.Append(cancelSource); il.Emit(OpCodes.Brfalse, afterSource);
        var callCancel = Instruction.Create(OpCodes.Ldloc, source);
        il.Append(callCancel); il.Emit(OpCodes.Callvirt, cancel); il.Emit(OpCodes.Leave, afterSource);
        il.Append(disposeSource); il.Emit(OpCodes.Callvirt, dispose); il.Emit(OpCodes.Endfinally);
        il.Append(afterSource); il.Emit(OpCodes.Endfinally);
        il.Append(restore); il.Emit(OpCodes.Stsfld, target);
        foreach (var pair in new[] { (callerToken, oldToken), (start, oldStart), (timeout, oldTimeout), (current, oldMain), (observedCompletion, oldCompletion) })
        { il.Emit(OpCodes.Ldloc, pair.Item2); il.Emit(OpCodes.Stsfld, pair.Item1); }
        il.Emit(OpCodes.Ldsfld, depth); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Sub); il.Emit(OpCodes.Stsfld, depth); il.Emit(OpCodes.Endfinally);
        il.Append(returnResult); il.Emit(OpCodes.Ret);
        entry.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = callCancel, TryEnd = disposeSource, HandlerStart = disposeSource, HandlerEnd = afterSource });
        entry.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = install, TryEnd = cancelSource, HandlerStart = cancelSource, HandlerEnd = restore });
        entry.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = install, TryEnd = restore, HandlerStart = restore, HandlerEnd = returnResult });

        // Copy the original entry validation INSIDE MRES so private IsDisposed
        // access remains valid; only the blocking implementation is redirected.
        var shim = New(mres, Prefix + "Wait", module.TypeSystem.Boolean,
            MethodAttributes.Assembly, module.TypeSystem.Int32, token);
        var originalGuard = wait.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Call
            && instruction.Operand is MethodReference method && method.FullName == "System.Boolean System.OperatingSystem::IsWasi()");
        code = shim.Body.GetILProcessor();
        // Preserve the complete original non-WASI entry, without running its
        // disposal/token/timeout validation twice. IsWasi is the same closed
        // platform predicate used by the existing TaskWait prologue.
        var selectedWasi = Instruction.Create(OpCodes.Nop);
        code.Emit(OpCodes.Call, (MethodReference)originalGuard.Operand); code.Emit(OpCodes.Brtrue, selectedWasi);
        code.Emit(OpCodes.Ldarg_0); code.Emit(OpCodes.Ldarg_1); code.Emit(OpCodes.Ldarg_2);
        code.Emit(OpCodes.Call, wait); code.Emit(OpCodes.Ret); code.Append(selectedWasi);
        foreach (var instruction in wait.Body.Instructions.TakeWhile(instruction => instruction != originalGuard))
        {
            Need((instruction.OpCode.FlowControl is FlowControl.Next or FlowControl.Call)
                && instruction.Operand is not VariableDefinition && instruction.Operand is not Instruction);
            var copied = Instruction.Create(OpCodes.Nop); copied.OpCode = instruction.OpCode;
            copied.Operand = instruction.Operand is ParameterDefinition parameter ? shim.Parameters[parameter.Index] : instruction.Operand;
            code.Append(copied);
        }
        code.Emit(OpCodes.Ldarg_0); code.Emit(OpCodes.Ldarg_1); code.Emit(OpCodes.Ldarg_2); code.Emit(OpCodes.Call, entry); code.Emit(OpCodes.Ret);
        var blocking = members[^1];
        var oldCall = blocking.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Callvirt
            && instruction.Operand is MethodReference method && method.Resolve() == wait);
        oldCall.Operand = shim;
        foreach (var method in members) RemoveGuard(method);
        // Removing a prefix does not widen any original remainder branch. The
        // sole blocking-call substitution keeps its original encoded width.
        VerifyRemainders(module, remainders);
        var timerPump = DetachTimerPumpBatch(module, reader);

        var receipt = new {
            patch = "latent.dotnet.wait-all.v2", profile = "dotnet-aggregate-task-wait-candidate-v2",
            originalMethods = Originals.Select((row, index) => new {
                method = members[index].FullName, token = row.Token, ilBytes = row.Bytes, ilSha256 = "sha256:" + row.Sha256 }).ToArray(),
            originalRemainders = remainders,
            rewrittenBodies = members.Append(check).Append(single).Append(ready).Append(body).Append(entry).Append(shim).Append(timerPump.Method)
                .ToDictionary(method => method.FullName, method => TaskWait.BodyIdentity(method)),
            timerPump = new {
                method = timerPump.Method.FullName, originalToken = 0x06003c90, originalIlBytes = 214,
                originalIlSha256 = "sha256:e486da68fcceeed848c7b35adbf5956f7345b9e3e63a05553148b83d2d7ba44b",
                originalBodyIdentity = timerPump.Original, rewrittenBodyIdentity = TaskWait.BodyIdentity(timerPump.Method),
                batch = "detach-positive-batch-to-original-List(Instances.Length)-before-original-enumerator",
                callbacks = "original-foreach-Clear-finally-FailFast-preserved", inverseExact = true,
                generatedHelpers = 0, generatedFields = 0, nativeOwners = 0,
            },
            countdown = "original-SetOnCountdownMres-completion-actions-detach-finally",
            waitEdge = "original-MRES-Wait-only", target = "private-aggregate-original-IsSet",
            deadline = "one-original-monotonic-interval-original-Task.Delay-wake",
            cancellation = "entry-token-before-IsSet;later-IsSet-before-token",
            context = "original-RunInternal-default-and-finally-restore",
            nesting = "single-and-aggregate-save-restore-depth32",
            zeroPoll = "original-bounded-pollable-detach-dispose",
            infiniteClock = "no-added-clock-read-or-timeout-wake",
            nonWasi = "original-MRES-Wait-entry-without-duplicate-validation",
            productionSelected = false, qualificationComplete = false, limitsChanged = false,
        };
        return (members.Append(check).Append(timerPump.Method).ToArray(), receipt, remainders, timerPump.Original);
    }

    internal static void VerifyRemainders(ModuleDefinition module, IReadOnlyDictionary<string, string> expected)
    {
        var all = module.GetTypes().SelectMany(type => type.Methods).ToArray();
        Need(expected.Count == 9);
        var originalWait = all.Single(method => method.DeclaringType.FullName == "System.Threading.ManualResetEventSlim"
            && method.Name == "Wait" && method.Parameters.Count == 2
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.Int32);
        foreach (var pair in expected)
        {
            var method = all.Single(method => method.FullName == pair.Key);
            if (method.Name != "WaitAllBlockingCore")
            {
                Need(TaskWait.BodyIdentity(method) == pair.Value);
                continue;
            }
            var call = method.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Callvirt
                && instruction.Operand is MethodReference reference
                && reference.DeclaringType.FullName == originalWait.DeclaringType.FullName
                && reference.Name == Prefix + "Wait");
            var selected = call.Operand;
            try
            {
                call.Operand = originalWait;
                Need(TaskWait.BodyIdentity(method) == pair.Value);
            }
            finally { call.Operand = selected; }
        }
    }

    internal static void VerifyDerivedLayout(ModuleDefinition module)
    {
        var selected = module.GetTypes().SelectMany(type => type.Methods)
            .Where(method => method.Name.StartsWith(Prefix, StringComparison.Ordinal)
                || method.DeclaringType.FullName == "System.Threading.Tasks.Task"
                    && (method.Name is "WaitAll" or "WaitAllCore" or "WaitAllBlockingCore")
                || method.DeclaringType.FullName == "System.Threading.WasiEventLoop"
                    && (method.Name is "CheckPollables" or "LsfWaitForActualTaskCompletion")
                || method.DeclaringType.FullName == "System.Threading.TimerQueue" && method.Name == "PumpTimerQueue").ToArray();
        Need(selected.Length == 16);
        foreach (var method in selected)
        {
            var instructions = method.Body.Instructions.ToArray();
            var boundaries = instructions.Select(instruction => instruction.Offset).Append(method.Body.CodeSize).ToHashSet();
            int next = 0;
            foreach (var instruction in instructions)
            {
                Need(instruction.Offset == next); next += instruction.GetSize();
                if (instruction.Operand is Instruction target)
                {
                    Need(instructions.Contains(target));
                    if (instruction.OpCode.OperandType == OperandType.ShortInlineBrTarget)
                        Need(target.Offset - next is >= sbyte.MinValue and <= sbyte.MaxValue);
                }
                else if (instruction.Operand is Instruction[] targets)
                    Need(targets.All(instructions.Contains));
            }
            Need(next == method.Body.CodeSize);
            var ranges = new List<(int Start, int End)>();
            foreach (var handler in method.Body.ExceptionHandlers)
            {
                int tryStart = handler.TryStart.Offset, tryEnd = handler.TryEnd?.Offset ?? next;
                int handlerStart = handler.HandlerStart.Offset, handlerEnd = handler.HandlerEnd?.Offset ?? next;
                Need(boundaries.Contains(tryStart) && boundaries.Contains(tryEnd)
                    && boundaries.Contains(handlerStart) && boundaries.Contains(handlerEnd)
                    && tryStart < tryEnd && handlerStart < handlerEnd
                    && (tryEnd <= handlerStart || handlerEnd <= tryStart));
                if (handler.HandlerType == ExceptionHandlerType.Filter)
                    Need(handler.FilterStart is not null && boundaries.Contains(handler.FilterStart.Offset)
                        && handler.FilterStart.Offset < handlerStart);
                else Need(handler.FilterStart is null);
                ranges.Add((tryStart, tryEnd)); ranges.Add((handlerStart, handlerEnd));
            }
            foreach (var left in ranges)
                foreach (var right in ranges)
                    Need(!(left.Start < right.Start && right.Start < left.End && left.End < right.End));
        }
    }
}

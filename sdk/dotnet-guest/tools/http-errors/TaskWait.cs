using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

// The existing WASI event-loop implementation is MIT licensed by the .NET
// Foundation. This selected compiler derivation retains its real work queue
// and poll semantics, while preserving TaskAwaiter's own fault propagation.
internal static class TaskWait
{
    internal const string SourceDigest = "29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735";
    private const string CecilDigest = "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7";
    private const string WaitDigest = "9b5bc35a1a68b80111c7eddc9cbc0903e6062d4e5e3b8f84e8f359445dd6e875";
    private const string LoopDigest = "1631857d71d2e5ecca2e22c95a6421aaecf016d9cba018412388b2d1c6646e19";
    private const string DispatchDigest = "05e0128b899121d13842a4c76993d2becaaebe2e57ecff53f1ea750ba39ba629";
    private const string ContextDigest = "865b97bff2c7df2a4ce36e8b802dc2a98f5865dbaf6119def4e85d21288afa29";
    private const string RestoreDigest = "d55f695b66f4e330e22b6e1d3aae2ce29c4d1ce059cf9c7a7b4afc0da9dc837a";
    private const string Helper = "LsfWaitForActualTaskCompletion";
    private const string Pump = "LsfDispatchUntilActualTaskCompletion";
    private const string Depth = "s_lsfTaskWaitDepth";

    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static string FileDigest(string path, long maximum)
    {
        var file = new FileInfo(path);
        if (!file.Exists || file.LinkTarget is not null || file.Length <= 0 || file.Length > maximum)
            throw new InvalidDataException("task-wait-invalid-material");
        return Hash(File.ReadAllBytes(path));
    }

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("task-wait-preimage-or-shape");
    }

    private static void Body(PEReader reader, MethodDefinition method, int bytes, string digest)
    {
        var code = System.Reflection.Metadata.PEReaderExtensions.GetMethodBody(reader, checked((int)method.RVA)).GetILBytes();
        Require(code is not null && code.Length == bytes && Hash(code) == digest);
    }

    private static string BodyIdentity(MethodDefinition method, int skip = 0)
    {
        if (!method.HasBody) return "no-body";
        var instructions = method.Body.Instructions.Skip(skip).ToList();
        string Target(Instruction? value) => value is null ? "end" : instructions.IndexOf(value) is var index && index >= 0
            ? index.ToString(System.Globalization.CultureInfo.InvariantCulture) : throw new InvalidDataException("task-wait-foreign-branch");
        string Operand(object? value) => value switch {
            null => "none", Instruction target => "branch:" + Target(target),
            Instruction[] targets => "switch:" + string.Join(",", targets.Select(Target)),
            MethodReference reference => "method:" + reference.FullName,
            FieldReference reference => "field:" + reference.FullName,
            TypeReference reference => "type:" + reference.FullName,
            CallSite call => "callsite:" + call.FullName,
            ParameterDefinition parameter => "parameter:" + parameter.Index,
            VariableDefinition variable => "local:" + variable.Index,
            string text => "string:" + text,
            IFormattable number => value.GetType().FullName + ":" + number.ToString(null, System.Globalization.CultureInfo.InvariantCulture),
            _ => throw new InvalidDataException("task-wait-unknown-operand"),
        };
        var value = JsonSerializer.Serialize(new {
            method.FullName, method.Attributes, method.ImplAttributes, method.CallingConvention, method.Body.InitLocals,
            locals = method.Body.Variables.Select(variable => variable.VariableType.FullName).ToArray(),
            instructions = instructions.Select(instruction => new { code = instruction.OpCode.Code.ToString(), operand = Operand(instruction.Operand) }).ToArray(),
            handlers = method.Body.ExceptionHandlers.Select(handler => new {
                kind = handler.HandlerType.ToString(), start = Target(handler.TryStart), end = Target(handler.TryEnd),
                handler = Target(handler.HandlerStart), handlerEnd = Target(handler.HandlerEnd), filter = Target(handler.FilterStart),
                catchType = handler.CatchType?.FullName,
            }).ToArray(),
        });
        return Hash(System.Text.Encoding.UTF8.GetBytes(value));
    }

    private static Dictionary<string, MethodDefinition> Methods(ModuleDefinition module) =>
        module.GetTypes().SelectMany(type => type.Methods.Select((method, index) =>
            new { key = type.FullName + "#" + index, method })).ToDictionary(item => item.key, item => item.method);

    internal static int Run(string[] args)
    {
        try
        {
            Require(args.Length == 3 && args.All(value => value.Length is > 0 and <= 4096));
            var original = Path.GetFullPath(args[0]);
            var output = Path.GetFullPath(args[1]);
            var receipt = Path.GetFullPath(args[2]);
            Require(original != output && original != receipt && output != receipt &&
                !File.Exists(output) && !Directory.Exists(output) && !File.Exists(receipt) && !Directory.Exists(receipt));
            Require(FileDigest(original, 8 * 1024 * 1024) == SourceDigest && new FileInfo(original).Length == 5694976);
            Require(FileDigest(typeof(ModuleDefinition).Assembly.Location, 512 * 1024) == CecilDigest);
            using var input = File.OpenRead(original);
            using var pe = new PEReader(input);
            using var module = ModuleDefinition.ReadModule(original, new ReaderParameters {
                ReadWrite = false, ReadSymbols = false, ReadingMode = ReadingMode.Deferred,
            });
            Require(module.Assembly.Name.Name == "System.Private.CoreLib" && module.Assembly.Name.Version == new Version(10, 0, 0, 0));
            var task = module.Types.Single(type => type.FullName == "System.Threading.Tasks.Task");
            var loop = module.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
            var queue = module.Types.Single(type => type.FullName == "System.Threading.ThreadPoolWorkQueue");
            var context = module.Types.Single(type => type.FullName == "System.Threading.ExecutionContext");
            var callback = module.Types.Single(type => type.FullName == "System.Threading.ContextCallback");
            var wait = task.Methods.Single(method => method.Name == "InternalWaitCore");
            var previousLoop = loop.Methods.Single(method => method.Name == "PollWasiEventLoopUntilResolvedVoid");
            var dispatch = queue.Methods.Single(method => method.Name == "Dispatch");
            var completed = task.Methods.Single(method => method.Name == "get_IsCompleted");
            var current = loop.Fields.Single(field => field.Name == "s_mainTask");
            var runContext = context.Methods.Single(method => method.Name == "RunInternal");
            var restoreContext = context.Methods.Single(method => method.Name == "RestoreChangedContextToThread");
            var defaultContext = context.Fields.Single(field => field.Name == "Default");
            var callbackConstructor = callback.Methods.Single(method => method.IsConstructor && method.Parameters.Count == 2);
            Require(!wait.IsStatic && wait.ReturnType.MetadataType == MetadataType.Boolean && wait.Parameters.Count == 2 &&
                wait.Parameters[0].ParameterType.MetadataType == MetadataType.Int32 &&
                wait.Parameters[1].ParameterType.FullName == "System.Threading.CancellationToken" &&
                current.IsStatic && current.FieldType.FullName == task.FullName &&
                dispatch.IsStatic && dispatch.Parameters.Count == 0 && dispatch.ReturnType.MetadataType == MetadataType.Boolean &&
                runContext.IsStatic && runContext.ReturnType.MetadataType == MetadataType.Void && runContext.Parameters.Count == 3 &&
                runContext.Parameters[0].ParameterType.FullName == context.FullName &&
                runContext.Parameters[1].ParameterType.FullName == callback.FullName &&
                runContext.Parameters[2].ParameterType.MetadataType == MetadataType.Object &&
                defaultContext.IsStatic && defaultContext.IsInitOnly && defaultContext.FieldType.FullName == context.FullName &&
                callback.BaseType.FullName == "System.MulticastDelegate" &&
                callbackConstructor.Parameters[0].ParameterType.MetadataType == MetadataType.Object &&
                callbackConstructor.Parameters[1].ParameterType.MetadataType == MetadataType.IntPtr &&
                !loop.Methods.Any(method => method.Name == Helper || method.Name == Pump) && !loop.Fields.Any(field => field.Name == Depth));
            Body(pe, wait, 224, WaitDigest);
            Body(pe, previousLoop, 44, LoopDigest);
            Body(pe, dispatch, 556, DispatchDigest);
            Body(pe, runContext, 132, ContextDigest);
            Body(pe, restoreContext, 37, RestoreDigest);
            var originalMap = Methods(module);
            var waitKey = originalMap.Single(item => item.Value == wait).Key;
            var originalMethods = originalMap.ToDictionary(item => item.Key, item => BodyIdentity(item.Value));
            var originalFields = module.GetTypes().SelectMany(type => type.Fields).Select(field => field.FullName).ToHashSet();
            var originalEntry = wait.Body.Instructions[0];
            Require(originalEntry.OpCode == OpCodes.Call && originalEntry.Operand is MethodReference isWasi &&
                isWasi.FullName == "System.Boolean System.OperatingSystem::IsWasi()" &&
                originalEntry.Next.OpCode == OpCodes.Brfalse_S && originalEntry.Next.Next.OpCode == OpCodes.Newobj &&
                originalEntry.Next.Next.Operand is MethodReference unsupported && unsupported.DeclaringType.FullName == "System.PlatformNotSupportedException" &&
                originalEntry.Next.Next.Next.OpCode == OpCodes.Throw);
            var canCancel = module.Types.Single(type => type.FullName == "System.Threading.CancellationToken")
                .Methods.Single(method => method.Name == "get_CanBeCanceled");
            var invalid = module.Types.Single(type => type.FullName == "System.InvalidOperationException")
                .Methods.Single(method => method.IsConstructor && method.Parameters.Count == 1 &&
                    method.Parameters[0].ParameterType.MetadataType == MetadataType.String);
            var depth = new FieldDefinition(Depth, FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Int32);
            loop.Fields.Add(depth);
            var pump = new MethodDefinition(Pump, MethodAttributes.Private | MethodAttributes.Static | MethodAttributes.HideBySig,
                module.TypeSystem.Void);
            pump.Parameters.Add(new ParameterDefinition(module.TypeSystem.Object));
            pump.Body.InitLocals = true;
            pump.Body.MaxStackSize = 1;
            var active = new VariableDefinition(task);
            pump.Body.Variables.Add(active);
            var dispatchIl = pump.Body.GetILProcessor();
            var again = dispatchIl.Create(OpCodes.Call, dispatch);
            var check = dispatchIl.Create(OpCodes.Ldloc, active);
            dispatchIl.Emit(OpCodes.Ldarg_0);
            dispatchIl.Emit(OpCodes.Castclass, task);
            dispatchIl.Emit(OpCodes.Stloc, active);
            dispatchIl.Emit(OpCodes.Br, check);
            dispatchIl.Append(again);
            dispatchIl.Emit(OpCodes.Pop);
            dispatchIl.Append(check);
            dispatchIl.Emit(OpCodes.Callvirt, completed);
            dispatchIl.Emit(OpCodes.Brfalse, again);
            dispatchIl.Emit(OpCodes.Ret);
            loop.Methods.Add(pump);
            var helper = new MethodDefinition(Helper, MethodAttributes.Assembly | MethodAttributes.Static | MethodAttributes.HideBySig,
                module.TypeSystem.Boolean);
            helper.Parameters.Add(new ParameterDefinition(task));
            helper.Body.InitLocals = true;
            helper.Body.MaxStackSize = 3;
            var previous = new VariableDefinition(task);
            helper.Body.Variables.Add(previous);
            var il = helper.Body.GetILProcessor();
            var admitted = il.Create(OpCodes.Ldsfld, current);
            var body = il.Create(OpCodes.Ldarg_0);
            var cleanup = il.Create(OpCodes.Ldloc, previous);
            var done = il.Create(OpCodes.Ldc_I4_1);
            il.Emit(OpCodes.Ldsfld, depth);
            il.Emit(OpCodes.Ldc_I4, 32);
            il.Emit(OpCodes.Blt, admitted);
            il.Emit(OpCodes.Ldstr, "activation-task-wait-depth-limit");
            il.Emit(OpCodes.Newobj, invalid);
            il.Emit(OpCodes.Throw);
            il.Append(admitted);
            il.Emit(OpCodes.Stloc, previous);
            il.Emit(OpCodes.Ldsfld, depth);
            il.Emit(OpCodes.Ldc_I4_1);
            il.Emit(OpCodes.Add);
            il.Emit(OpCodes.Stsfld, depth);
            il.Append(body);
            il.Emit(OpCodes.Stsfld, current);
            // Dispatch deliberately enters with default contexts. RunInternal
            // restores the raw caller context (including suppressed flow),
            // SynchronizationContext and AsyncLocal notifications on every exit.
            il.Emit(OpCodes.Ldsfld, defaultContext);
            il.Emit(OpCodes.Ldnull);
            il.Emit(OpCodes.Ldftn, pump);
            il.Emit(OpCodes.Newobj, callbackConstructor);
            il.Emit(OpCodes.Ldarg_0);
            il.Emit(OpCodes.Call, runContext);
            il.Emit(OpCodes.Leave, done);
            il.Append(cleanup);
            il.Emit(OpCodes.Stsfld, current);
            il.Emit(OpCodes.Ldsfld, depth);
            il.Emit(OpCodes.Ldc_I4_1);
            il.Emit(OpCodes.Sub);
            il.Emit(OpCodes.Stsfld, depth);
            il.Emit(OpCodes.Endfinally);
            il.Append(done);
            il.Emit(OpCodes.Ret);
            helper.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
                TryStart = body, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
            });
            loop.Methods.Add(helper);
            var entry = wait.Body.GetILProcessor();
            // Retain the complete original method and its original unsupported
            // finite/cancellable path. Only a selected ordinary infinite join
            // enters the real WASI queue; it never invents a completed Task.
            Instruction[] prologue = [
                entry.Create(OpCodes.Call, (MethodReference)originalEntry.Operand),
                entry.Create(OpCodes.Brfalse, originalEntry),
                entry.Create(OpCodes.Ldarg_1), entry.Create(OpCodes.Ldc_I4_M1),
                entry.Create(OpCodes.Bne_Un, originalEntry), entry.Create(OpCodes.Ldarga, wait.Parameters[1]),
                entry.Create(OpCodes.Call, canCancel), entry.Create(OpCodes.Brtrue, originalEntry),
                entry.Create(OpCodes.Ldarg_0), entry.Create(OpCodes.Call, helper), entry.Create(OpCodes.Ret),
            ];
            foreach (var instruction in prologue) entry.InsertBefore(originalEntry, instruction);
            var timerMethods = IdleTimerDriver.Install(module);
            var timerOriginalBodies = timerMethods.ToDictionary(method => method.FullName,
                method => originalMethods[originalMap.Single(item => item.Value == method).Key]);
            var timerModifiedBodies = timerMethods.ToDictionary(method => originalMap.Single(item => item.Value == method).Key,
                method => BodyIdentity(method));
            var generatedHelpers = Methods(module).Where(item => !originalMap.ContainsKey(item.Key))
                .ToDictionary(item => item.Value.FullName, item => BodyIdentity(item.Value));
            Require(generatedHelpers.Count == 8 && timerModifiedBodies.Count == 3);
            module.Write(output, new WriterParameters { WriteSymbols = false, DeterministicMvid = true });
            using (var written = ModuleDefinition.ReadModule(output))
            {
                var methods = Methods(written);
                Require(methods.Count == originalMethods.Count + 8 &&
                    methods.Values.Count(method => method.FullName == helper.FullName) == 1 &&
                    methods.Values.Count(method => method.FullName == pump.FullName) == 1);
                foreach (var (name, identity) in originalMethods)
                    Require(methods.ContainsKey(name) && (timerModifiedBodies.TryGetValue(name, out var modified)
                        ? BodyIdentity(methods[name]) == modified
                        : BodyIdentity(methods[name], name == waitKey ? prologue.Length : 0) == identity));
                foreach (var (name, identity) in generatedHelpers)
                    Require(BodyIdentity(methods.Values.Single(method => method.FullName == name)) == identity);
                var fields = written.GetTypes().SelectMany(type => type.Fields).Select(field => field.FullName).ToHashSet();
                var addedFields = module.GetTypes().SelectMany(type => type.Fields).Select(field => field.FullName)
                    .Where(name => !originalFields.Contains(name)).ToHashSet();
                Require(addedFields.Count == 5 && fields.Count == originalFields.Count + 5 &&
                    fields.Except(addedFields).ToHashSet().SetEquals(originalFields) && addedFields.IsSubsetOf(fields));
            }
            Require(FileDigest(original, 8 * 1024 * 1024) == SourceDigest);
            var result = new {
                patch = "latent.dotnet.stackful-task-wait.v1", sourceDigest = "sha256:" + SourceDigest,
                outputDigest = "sha256:" + FileDigest(output, 8 * 1024 * 1024), cecilDigest = "sha256:" + CecilDigest,
                method = wait.FullName, originalWaitBodyDigest = "sha256:" + WaitDigest,
                originalLoopBodyDigest = "sha256:" + LoopDigest, originalDispatchBodyDigest = "sha256:" + DispatchDigest,
                originalContextBodyDigest = "sha256:" + ContextDigest, originalContextRestoreBodyDigest = "sha256:" + RestoreDigest,
                maximumNestedWaits = 32, finiteAndCancellableWaits = "original-unsupported",
                completion = "actual-task-only", exceptionPropagation = "original-TaskAwaiter",
                nestedTaskIdentity = "save-restore-finally", defaultClientComponentQualified = false,
                callerContexts = "original-RunInternal-Default", contextNotifications = "original-runtime",
                generatedHelperCount = 8, contextCallback = "same-CoreLib-ContextCallback(object)",
                unchangedOriginalMethods = originalMethods.Count - 4, completeOriginalWaitRemainderPreserved = true,
                timerDriver = "TimerQueue.SetNextTimer-only", timerDriverIdle = "Timer.ActiveCount==0",
                timerDriverCancellation = "original-CancellationTokenSource-CancelAndDispose",
                timerDriverIdentity = "original-task-reference-and-epoch", timerDriverCallbacks = "original-queued-user-callbacks-preserved",
                timerDriverScheduledToFire = "untouched", timerDriverCacheCleanup = false,
                timerDriverRegistrationContext = "no-new-capture-original-flow-restored",
                timerDriverModifiedOriginalMethods = 3, timerDriverOriginalBodies = timerOriginalBodies,
            };
            using var destination = new FileStream(receipt, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(destination, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
            return 0;
        }
        catch (Exception)
        {
            Console.Error.WriteLine("task-wait-patch-failed");
            return 1;
        }
    }
}

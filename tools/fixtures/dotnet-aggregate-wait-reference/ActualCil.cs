using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using CecilOpCodes = Mono.Cecil.Cil.OpCodes;
using CecilOperandType = Mono.Cecil.Cil.OperandType;
using CecilCode = Mono.Cecil.Cil.Code;

// HOST REFERENCE ONLY. No rewritten CoreLib is loaded as a CLR runtime.
// Keep raw instructions/branches/EH; change only explicitly recorded tokens.
internal sealed class ActualCil : IDisposable
{
    private readonly FileStream input;
    private readonly PEReader reader;
    private readonly ModuleDefinition module;
    private readonly Dictionary<string, DynamicMethod> methods = new();
    private readonly Dictionary<string, MethodDefinition> source = new();
    private readonly HashSet<string> mappings = new();
    private readonly HashSet<string> throwSites = new();
    private readonly List<object> throwCalls = new();
    private static readonly HashSet<string> ExpectedThrowSites = [
        "System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[])@5|NullByName|51",
        "System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.TimeSpan)@34|RangeByName|62",
        "System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.TimeSpan)@44|NullByName|51",
        "System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32)@5|NullByName|51",
        "System.Void System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Threading.CancellationToken)@5|NullByName|51",
        "System.Boolean System.Threading.Tasks.Task::WaitAll(System.Threading.Tasks.Task[],System.Int32,System.Threading.CancellationToken)@5|NullByName|51",
        "System.Void System.Threading.Tasks.Task::WaitAll(System.Collections.Generic.IEnumerable`1<System.Threading.Tasks.Task>,System.Threading.CancellationToken)@5|NullByName|51",
        "System.Boolean System.Threading.Tasks.Task::WaitAllCore(System.ReadOnlySpan`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)@6|RangeByName|60",
        "System.Boolean System.Threading.Tasks.Task::WaitAllCore(System.ReadOnlySpan`1<System.Threading.Tasks.Task>,System.Int32,System.Threading.CancellationToken)@68|ArgumentByName|47,51",
    ];
    private readonly Assembly core = typeof(Task).Assembly;
    private const BindingFlags Members = BindingFlags.Public | BindingFlags.NonPublic
        | BindingFlags.Instance | BindingFlags.Static;

    internal ActualCil(string path)
    {
        input = File.OpenRead(path); reader = new PEReader(input);
        module = ModuleDefinition.ReadModule(path);
        var names = new HashSet<string> {
            "LsfAggregateReady", "LsfAggregateDispatch", "LsfAggregateWait",
            "LsfWaitForActualTaskCompletion", "LsfDispatchUntilActualTaskCompletion" };
        foreach (var method in module.GetTypes().SelectMany(type => type.Methods))
        {
            bool selected = method.DeclaringType.FullName == "System.Threading.Tasks.Task"
                && (method.Name is "WaitAll" or "WaitAllCore" or "WaitAllBlockingCore")
                || method.DeclaringType.FullName == "System.Threading.WasiEventLoop" && names.Contains(method.Name)
                || method.DeclaringType.FullName == "System.Threading.ManualResetEventSlim" && method.Name == "LsfAggregateWait"
                || method.DeclaringType.FullName == "System.Threading.TimeoutHelper" && method.Name == "UpdateTimeOut";
            if (!selected) continue;
            Need(method.HasBody && !method.HasGenericParameters
                && Modifiers(method.ReturnType).Count == 0
                && method.Parameters.All(parameter => Modifiers(parameter.ParameterType).Count == 0), "copy-method-shape");
            source.Add(method.FullName, method);
            var parameters = method.Parameters.Select(parameter => HostType(parameter.ParameterType)).ToList();
            if (method.HasThis) parameters.Insert(0, HostType(method.DeclaringType));
            methods.Add(method.FullName, new DynamicMethod("Reference_" + method.Name,
                HostType(method.ReturnType), parameters.ToArray(), typeof(ActualCil).Module, skipVisibility: true)
                { InitLocals = method.Body.InitLocals });
        }
        Need(source.Count == 16, "closed-sixteen-method-copy");
        ThrowHelperPorts.Bind(module);
        foreach (var pair in source) Copy(pair.Value, methods[pair.Key]);
        Need(throwSites.SetEquals(ExpectedThrowSites), "exact-nine-throw-helper-sites");
    }

    internal static void Need(bool value, string code)
    { if (!value) throw new InvalidOperationException("aggregate-reference:" + code); }

    internal T Delegate<T>(string name) where T : Delegate => methods[name].CreateDelegate<T>();
    internal object Observation() => new {
        copiedMethods = source.OrderBy(pair => pair.Key).Select(pair => new {
            method = pair.Key, ilSha256 = Digest(Code(pair.Value)),
            normalizedBodySha256 = BodyIdentity(pair.Value),
            locals = pair.Value.Body.Variables.Select(variable => variable.VariableType.FullName).ToArray(),
            handlers = pair.Value.Body.ExceptionHandlers.Select(handler => new {
                kind = handler.HandlerType.ToString(), start = handler.TryStart.Offset,
                end = handler.TryEnd?.Offset ?? pair.Value.Body.CodeSize,
                handlerStart = handler.HandlerStart.Offset,
                handlerEnd = handler.HandlerEnd?.Offset ?? pair.Value.Body.CodeSize }).ToArray() }).ToArray(),
        tokenMap = mappings.Order().ToArray(), originalInstructionsBranchesAndEhCopied = true,
        throwHelperBindings = ThrowHelperPorts.Bindings, throwHelperMethods = ThrowHelperPorts.MethodBindings(),
        throwHelperCalls = throwCalls, privateThrowHelperEnumsTranslatedByName = true,
        pinnedWasiCountdownClassExecuted = false, hostPrivateCountdownCounterpart = true,
        nativeWasiPollAndLedgerQualified = false, runtimeAddressesRetained = false,
    };

    private static string Digest(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    // Same normalized representation as the maintained TaskWait validator.
    // The controller compares these to the ACTUAL emitted candidate receipt.
    private static string BodyIdentity(MethodDefinition method)
    {
        var instructions = method.Body.Instructions.ToList();
        string Target(Instruction? value) => value is null ? "end" : instructions.IndexOf(value) is var index && index >= 0
            ? index.ToString(System.Globalization.CultureInfo.InvariantCulture)
            : throw new InvalidDataException("aggregate-reference:foreign-branch");
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
            _ => throw new InvalidDataException("aggregate-reference:unknown-operand"),
        };
        return Digest(System.Text.Encoding.UTF8.GetBytes(System.Text.Json.JsonSerializer.Serialize(new {
            method.FullName, method.Attributes, method.ImplAttributes, method.CallingConvention, method.Body.InitLocals,
            locals = method.Body.Variables.Select(variable => variable.VariableType.FullName).ToArray(),
            instructions = instructions.Select(instruction => new { code = instruction.OpCode.Code.ToString(), operand = Operand(instruction.Operand) }).ToArray(),
            handlers = method.Body.ExceptionHandlers.Select(handler => new {
                kind = handler.HandlerType.ToString(), start = Target(handler.TryStart), end = Target(handler.TryEnd),
                handler = Target(handler.HandlerStart), handlerEnd = Target(handler.HandlerEnd), filter = Target(handler.FilterStart),
                catchType = handler.CatchType?.FullName,
            }).ToArray(),
        })));
    }
    private byte[] Code(MethodDefinition method) => System.Reflection.Metadata.PEReaderExtensions
        .GetMethodBody(reader, checked((int)method.RVA)).GetILBytes()
        ?? throw new InvalidOperationException("aggregate-reference:no-original-il");

    private Type HostType(TypeReference type)
    {
        if (type is IModifierType modifier) return HostType(modifier.ElementType);
        if (type is ByReferenceType reference) return HostType(reference.ElementType).MakeByRefType();
        if (type is PointerType pointer) return HostType(pointer.ElementType).MakePointerType();
        if (type is ArrayType array)
        { Need(array.IsVector, "array-shape"); return HostType(array.ElementType).MakeArrayType(); }
        if (type is GenericInstanceType generic)
            return HostType(generic.ElementType).MakeGenericType(generic.GenericArguments.Select(HostType).ToArray());
        if (type is GenericParameter) throw new InvalidOperationException("aggregate-reference:unbound-generic-type");
        if (type.FullName == "System.Threading.CancellationTokenSource") return typeof(OwnedSource);
        var found = core.GetType(type.FullName.Replace('/', '+'), throwOnError: false);
        Need(found is not null, "missing-host-type:" + type.FullName);
        if (found!.IsEnum)
        {
            var original = type.Resolve();
            Need(original.Module == module && original.IsEnum, "enum-source-scope");
            var declared = original.Fields.Where(field => field.IsLiteral).ToArray();
            foreach (var field in declared)
                Need(Enum.GetNames(found).Contains(field.Name)
                    && Convert.ToInt64(Enum.Parse(found, field.Name)) == Convert.ToInt64(field.Constant),
                    "host-enum-value-mismatch:" + type.FullName + "." + field.Name);
        }
        return found!;
    }

    private string Canonical(TypeReference type, TypeReference? context = null, GenericInstanceMethod? call = null)
    {
        if (type is IModifierType modifier) return Canonical(modifier.ElementType, context, call);
        if (type is GenericParameter parameter)
        {
            if (parameter.Type == GenericParameterType.Type && context is GenericInstanceType owner)
                return Canonical(owner.GenericArguments[parameter.Position]);
            if (parameter.Type == GenericParameterType.Method && call is not null)
                return Canonical(call.GenericArguments[parameter.Position]);
            return (parameter.Type == GenericParameterType.Method ? "!!" : "!") + parameter.Position;
        }
        if (type is ByReferenceType reference) return Canonical(reference.ElementType, context, call) + "&";
        if (type is ArrayType array) return Canonical(array.ElementType, context, call) + "[]";
        if (type is GenericInstanceType generic) return Canonical(generic.ElementType) + "<"
            + string.Join(',', generic.GenericArguments.Select(argument => Canonical(argument, context, call))) + ">";
        return HostType(type).FullName ?? throw new InvalidOperationException("aggregate-reference:nameless-type");
    }

    private static string Canonical(Type type)
    {
        if (type.IsGenericParameter) return (type.DeclaringMethod is null ? "!" : "!!") + type.GenericParameterPosition;
        if (type.IsByRef) return Canonical(type.GetElementType()!) + "&";
        if (type.IsArray) return Canonical(type.GetElementType()!) + "[]";
        if (type.IsGenericType) return type.GetGenericTypeDefinition().FullName + "<"
            + string.Join(',', type.GetGenericArguments().Select(Canonical)) + ">";
        return type.FullName ?? throw new InvalidOperationException("aggregate-reference:nameless-host-type");
    }

    private static List<(bool Required, string Name)> Modifiers(TypeReference type)
    {
        var result = new List<(bool, string)>();
        while (type is IModifierType || type is ByReferenceType)
        {
            if (type is IModifierType modifier)
            {
                result.Add((type is RequiredModifierType, modifier.ModifierType.FullName.Replace('/', '+')));
                type = modifier.ElementType;
            }
            else type = ((ByReferenceType)type).ElementType;
        }
        // No silently flattened modifiers within generic/array element signatures.
        if (type is GenericInstanceType generic)
            Need(generic.GenericArguments.All(argument => Modifiers(argument).Count == 0), "nested-generic-modifier");
        if (type is ArrayType array) Need(Modifiers(array.ElementType).Count == 0, "nested-array-modifier");
        return result;
    }

    private bool Signature(ParameterInfo host, TypeReference sourceType, TypeReference context, GenericInstanceMethod? call)
    {
        var modifiers = Modifiers(sourceType);
        return Canonical(host.ParameterType) == Canonical(sourceType, context, call)
            && host.GetRequiredCustomModifiers().Select(type => type.FullName)
                .SequenceEqual(modifiers.Where(value => value.Required).Select(value => value.Name))
            && host.GetOptionalCustomModifiers().Select(type => type.FullName)
                .SequenceEqual(modifiers.Where(value => !value.Required).Select(value => value.Name));
    }

    private MethodBase HostMethod(MethodReference reference)
    {
        var call = reference as GenericInstanceMethod;
        var element = call?.ElementMethod ?? reference;
        var owner = HostType(element.DeclaringType);
        IEnumerable<MethodBase> candidates = element.Name == ".ctor"
            ? owner.GetConstructors(Members) : owner.GetMethods(Members).Where(method => method.Name == element.Name);
        var matches = new List<MethodBase>();
        foreach (var candidate in candidates)
        {
            if (candidate.IsStatic == element.HasThis) continue;
            MethodBase resolved = candidate;
            if (call is not null)
            {
                if (candidate is not MethodInfo generic || !generic.IsGenericMethodDefinition
                    || generic.GetGenericArguments().Length != call.GenericArguments.Count) continue;
                resolved = generic.MakeGenericMethod(call.GenericArguments.Select(HostType).ToArray());
            }
            else if (candidate is MethodInfo generic && generic.IsGenericMethodDefinition != element.HasGenericParameters) continue;
            var parameters = resolved.GetParameters();
            if (parameters.Length != element.Parameters.Count
                || parameters.Where((parameter, index) => !Signature(parameter,
                    element.Parameters[index].ParameterType, element.DeclaringType, call)).Any()) continue;
            if (resolved is MethodInfo result && !Signature(result.ReturnParameter,
                element.ReturnType, element.DeclaringType, call)) continue;
            matches.Add(resolved);
        }
        Need(matches.Count == 1, "host-member-mismatch:" + reference.FullName);
        mappings.Add(reference.FullName + " => " + matches[0]);
        return matches[0];
    }

    private FieldInfo HostField(FieldReference field)
    {
        FieldInfo? mapped = field.DeclaringType.FullName == "System.Threading.WasiEventLoop"
            ? typeof(Ports).GetField(field.Name, Members) : HostType(field.DeclaringType).GetField(field.Name, Members);
        Need(mapped is not null && mapped.FieldType == HostType(field.FieldType)
            && mapped.IsStatic == field.Resolve().IsStatic, "host-field-mismatch:" + field.FullName);
        mappings.Add(field.FullName + " => " + mapped);
        return mapped!;
    }

    private int Token(DynamicILInfo info, Instruction instruction, MethodDefinition caller)
    {
        if (instruction.Operand is string literal) return info.GetTokenFor(literal);
        if (instruction.Operand is TypeReference type) return info.GetTokenFor(HostType(type).TypeHandle);
        if (instruction.Operand is FieldReference field)
        {
            var mapped = HostField(field);
            return info.GetTokenFor(mapped.FieldHandle, mapped.DeclaringType!.TypeHandle);
        }
        if (instruction.Operand is not MethodReference method)
            throw new InvalidOperationException("aggregate-reference:unsupported-token");
        var throwing = ThrowHelperPorts.Port(method.FullName);
        if (throwing is not null)
        {
            Need(instruction.OpCode == CecilOpCodes.Call && method.Resolve().Module == module,
                "throw-helper-original-call");
            int index = caller.Body.Instructions.IndexOf(instruction);
            int count = method.Parameters.Count;
            Need(count is 1 or 2 && index >= count, "throw-helper-argument-count");
            var constants = caller.Body.Instructions.Skip(index - count).Take(count).Select(Integer).ToArray();
            string site = caller.FullName + "@" + instruction.Offset + "|" + throwing.Name + "|" + string.Join(',', constants);
            Need(ExpectedThrowSites.Contains(site) && throwSites.Add(site), "throw-helper-closed-callsite");
            throwCalls.Add(new { caller = caller.FullName, offset = instruction.Offset, helper = method.FullName, constants });
            mappings.Add(method.FullName + " => explicit-host-port:" + throwing.Name);
            return info.GetTokenFor(throwing.MethodHandle);
        }
        MethodInfo? port = method.FullName switch {
            "System.Boolean System.OperatingSystem::IsWasi()" => typeof(Ports).GetMethod(nameof(Ports.IsWasi)),
            "System.Boolean System.Threading.ManualResetEventSlim::get_IsDisposed()" => typeof(Ports).GetMethod(nameof(Ports.CopiedDisposed)),
            "System.Int64 System.Environment::get_TickCount64()" => typeof(Ports).GetMethod(
                caller.DeclaringType.FullName == "System.Threading.TimeoutHelper"
                    ? nameof(Ports.RemainingClock) : nameof(Ports.StartClock)),
            "System.Boolean System.Threading.ThreadPoolWorkQueue::Dispatch()" => typeof(Ports).GetMethod(nameof(Ports.Dispatch)),
            "System.Void Lsf.CompilerOwned.ManagedWorkRuntime::EnsureJoinReady()" => typeof(Ports).GetMethod(nameof(Ports.EnsureReady)),
            "System.Threading.Tasks.Task System.Threading.Tasks.Task::Delay(System.Int32,System.Threading.CancellationToken)" => typeof(Ports).GetMethod(nameof(Ports.Delay)),
            _ => null,
        };
        if (instruction.OpCode == CecilOpCodes.Ldftn)
        {
            port = method.FullName switch {
                "System.Void System.Threading.WasiEventLoop::LsfAggregateDispatch(System.Object)" => typeof(Ports).GetMethod(nameof(Ports.AggregateBridge)),
                "System.Void System.Threading.WasiEventLoop::LsfDispatchUntilActualTaskCompletion(System.Object)" => typeof(Ports).GetMethod(nameof(Ports.SingleBridge)),
                _ => throw new InvalidOperationException("aggregate-reference:unexpected-delegate-target"),
            };
        }
        if (port is not null)
        {
            var expected = method.Parameters.Select(parameter => HostType(parameter.ParameterType)).ToList();
            if (method.HasThis) expected.Insert(0, HostType(method.DeclaringType));
            Need(port.IsStatic && port.ReturnType == HostType(method.ReturnType)
                && port.GetParameters().Select(parameter => parameter.ParameterType).SequenceEqual(expected),
                "host-port-signature-mismatch");
            mappings.Add(method.FullName + " => explicit-host-port:" + port.Name);
            return info.GetTokenFor(port.MethodHandle);
        }
        if (methods.TryGetValue(method.FullName, out var copied)) return info.GetTokenFor(copied);
        var host = HostMethod(method);
        return info.GetTokenFor(host.MethodHandle, host.DeclaringType!.TypeHandle);
    }

    private static int Integer(Instruction instruction) => instruction.OpCode.Code switch {
        CecilCode.Ldc_I4 => (int)instruction.Operand, CecilCode.Ldc_I4_S => (sbyte)instruction.Operand,
        CecilCode.Ldc_I4_M1 => -1, CecilCode.Ldc_I4_0 => 0, CecilCode.Ldc_I4_1 => 1, CecilCode.Ldc_I4_2 => 2,
        CecilCode.Ldc_I4_3 => 3, CecilCode.Ldc_I4_4 => 4, CecilCode.Ldc_I4_5 => 5, CecilCode.Ldc_I4_6 => 6,
        CecilCode.Ldc_I4_7 => 7, CecilCode.Ldc_I4_8 => 8,
        _ => throw new InvalidDataException("aggregate-reference:throw-helper-nonconstant"),
    };

    private void Copy(MethodDefinition method, DynamicMethod copy)
    {
        var info = copy.GetDynamicILInfo();
        var code = Code(method);
        foreach (var instruction in method.Body.Instructions)
        {
            var kind = instruction.OpCode.OperandType;
            if (kind is CecilOperandType.InlineMethod or CecilOperandType.InlineField or CecilOperandType.InlineType
                or CecilOperandType.InlineTok or CecilOperandType.InlineString)
                BitConverter.GetBytes(Token(info, instruction, method)).CopyTo(code, instruction.Offset + instruction.OpCode.Size);
            else Need(kind != CecilOperandType.InlineSig, "unsupported-calli-signature");
        }
        var locals = SignatureHelper.GetLocalVarSigHelper();
        foreach (var variable in method.Body.Variables)
        {
            var type = variable.VariableType;
            bool pinned = type is PinnedType;
            Need(Modifiers(pinned ? ((PinnedType)type).ElementType : type).Count == 0, "modified-local-signature");
            locals.AddArgument(HostType(pinned ? ((PinnedType)type).ElementType : type), pinned);
        }
        info.SetLocalSignature(locals.GetSignature());
        info.SetCode(code, method.Body.MaxStackSize);
        if (method.Body.ExceptionHandlers.Count == 0) return;
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
        int length = 4 + 24 * method.Body.ExceptionHandlers.Count;
        writer.Write((byte)0x41); writer.Write((byte)length); writer.Write((byte)(length >> 8)); writer.Write((byte)(length >> 16));
        foreach (var handler in method.Body.ExceptionHandlers)
        {
            int start = handler.TryStart.Offset, end = handler.TryEnd?.Offset ?? method.Body.CodeSize;
            int body = handler.HandlerStart.Offset, bodyEnd = handler.HandlerEnd?.Offset ?? method.Body.CodeSize;
            writer.Write((int)handler.HandlerType); writer.Write(start); writer.Write(end - start);
            writer.Write(body); writer.Write(bodyEnd - body);
            writer.Write(handler.HandlerType == ExceptionHandlerType.Catch
                ? info.GetTokenFor(HostType(handler.CatchType).TypeHandle)
                : handler.HandlerType == ExceptionHandlerType.Filter ? handler.FilterStart.Offset : 0);
        }
        info.SetExceptions(stream.ToArray());
    }

    public void Dispose() { module.Dispose(); reader.Dispose(); input.Dispose(); }
}

using Mono.Cecil;
using Mono.Cecil.Cil;

// Selected only after authentication of the complete original WASI CoreLib.
// Every edit is to one enumerated producer or an exact call inside that producer.
internal sealed class ManagedWorkHooks
{
    private readonly ModuleDefinition module;
    private readonly IReadOnlyDictionary<string, MethodDefinition> registry;
    private readonly HashSet<MethodDefinition> changed = new();
    private readonly List<MethodDefinition> added = new();

    internal ManagedWorkHooks(ModuleDefinition module, IReadOnlyDictionary<string, MethodDefinition> registry)
    {
        this.module = module; this.registry = registry;
    }

    private static void Need(bool value)
    {
        if (!value) throw new InvalidDataException("managed-work-producer-preimage");
    }

    private TypeDefinition Type(string name) => module.GetTypes().Single(type => type.FullName == name);
    private MethodDefinition Hook(string name) => registry.Values.Single(method => method.Name == name);

    private static void Before(MethodDefinition method, Instruction anchor, params Instruction[] instructions)
    {
        // Branches and EH boundaries that entered the original instruction must
        // also execute the inserted admission. Existing handlers remain intact.
        var first = instructions[0];
        foreach (var instruction in method.Body.Instructions)
        {
            if (ReferenceEquals(instruction.Operand, anchor)) instruction.Operand = first;
            else if (instruction.Operand is Instruction[] targets)
                for (int i = 0; i < targets.Length; i++) if (ReferenceEquals(targets[i], anchor)) targets[i] = first;
        }
        foreach (var handler in method.Body.ExceptionHandlers)
        {
            if (handler.TryStart == anchor) handler.TryStart = first;
            if (handler.TryEnd == anchor) handler.TryEnd = first;
            if (handler.HandlerStart == anchor) handler.HandlerStart = first;
            if (handler.HandlerEnd == anchor) handler.HandlerEnd = first;
            if (handler.FilterStart == anchor) handler.FilterStart = first;
        }
        var il = method.Body.GetILProcessor();
        foreach (var instruction in instructions) il.InsertBefore(anchor, instruction);
    }

    private void Prefix(MethodDefinition method, string hook, params Instruction[] arguments)
    {
        Before(method, method.Body.Instructions[0], arguments.Append(Instruction.Create(OpCodes.Call, Hook(hook))).ToArray());
        changed.Add(method);
    }

    private MethodDefinition New(TypeDefinition type, string name, TypeReference result,
        MethodAttributes attributes, params TypeReference[] parameters)
    {
        Need(!type.Methods.Any(method => method.Name == name));
        var method = new MethodDefinition(name, attributes | MethodAttributes.HideBySig, result);
        foreach (var parameter in parameters) method.Parameters.Add(new ParameterDefinition(parameter));
        type.Methods.Add(method); added.Add(method); return method;
    }

    private void CapturedContext()
    {
        var contract = Type("Lsf.CompilerOwned.ManagedWorkRuntime/ContextSource");
        var declaration = contract.Methods.Single();
        var context = Type("System.Threading.ExecutionContext");
        var task = Type("System.Threading.Tasks.Task");
        var source = New(task, "LsfCapturedWorkContext", context,
            MethodAttributes.Public | MethodAttributes.Virtual | MethodAttributes.NewSlot);
        source.Overrides.Add(declaration);
        task.Interfaces.Add(new InterfaceImplementation(contract));
        var il = source.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, task.Methods.Single(method => method.Name == "get_CapturedContext"));
        il.Emit(OpCodes.Ret);

        var bind = New(task, "LsfBindWorkContext", module.TypeSystem.Void,
            MethodAttributes.Assembly | MethodAttributes.Virtual | MethodAttributes.NewSlot, context);
        il = bind.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Call, task.Methods.Single(method => method.Name == "set_CapturedContext")); il.Emit(OpCodes.Ret);

        var box = Type("System.Runtime.CompilerServices.AsyncTaskMethodBuilder`1/AsyncStateMachineBox`1");
        var boxSource = New(box, "LsfCapturedWorkContext", context, MethodAttributes.Public | MethodAttributes.Virtual);
        boxSource.Overrides.Add(source);
        var get = box.Methods.Single(method => method.Name == "get_Context");
        Need(get.ReturnType is ByReferenceType reference && reference.ElementType.FullName == context.FullName);
        il = boxSource.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, Self(get)); il.Emit(OpCodes.Ldind_Ref); il.Emit(OpCodes.Ret);
        var boxBind = New(box, "LsfBindWorkContext", module.TypeSystem.Void,
            MethodAttributes.Assembly | MethodAttributes.Virtual, context);
        boxBind.Overrides.Add(bind);
        il = boxBind.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, Self(get)); il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Stind_Ref); il.Emit(OpCodes.Ret);
        var bindStub = Hook("BindAsyncContext"); bindStub.Body = new MethodBody(bindStub);
        il = bindStub.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Callvirt, declaration);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, Hook("BindContext")); il.Emit(OpCodes.Callvirt, bind); il.Emit(OpCodes.Ret);

        foreach (string name in new[] { "QueueUserWorkItemCallback", "QueueUserWorkItemCallback`1",
            "QueueUserWorkItemCallbackDefaultContext", "QueueUserWorkItemCallbackDefaultContext`1" })
        {
            var type = Type("System.Threading." + name);
            var getter = New(type, "LsfCapturedWorkContext", context,
                MethodAttributes.Public | MethodAttributes.Virtual | MethodAttributes.Final | MethodAttributes.NewSlot);
            getter.Overrides.Add(declaration); type.Interfaces.Add(new InterfaceImplementation(contract));
            il = getter.Body.GetILProcessor();
            var field = type.Fields.SingleOrDefault(candidate => candidate.Name == "_context");
            if (field is null) il.Emit(OpCodes.Ldnull);
            else { il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldfld, Self(field)); }
            il.Emit(OpCodes.Ret);
            if (field is not null)
            {
                var execute = type.Methods.Single(method => method.Name == "Execute");
                var loads = execute.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ldfld
                    && instruction.Operand is FieldReference selected && selected.Resolve() == field).ToArray();
                Need(loads.Length == 1);
                il = execute.Body.GetILProcessor();
                var item = Instruction.Create(OpCodes.Ldarg_0);
                il.InsertAfter(loads[0], item);
                il.InsertAfter(item, Instruction.Create(OpCodes.Call, Hook("BindContext")));
                changed.Add(execute);
            }
            else ScopeCallback(type.Methods.Single(method => method.Name == "Execute"));
        }
    }

    private void ScopeCallback(MethodDefinition execute)
    {
        Need(execute.ReturnType.MetadataType == MetadataType.Void && execute.Body.ExceptionHandlers.Count == 0);
        var original = execute.Body.Instructions[0];
        var previous = new VariableDefinition(module.TypeSystem.Object);
        execute.Body.InitLocals = true; execute.Body.Variables.Add(previous);
        Before(execute, original, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("Enter")),
            Instruction.Create(OpCodes.Stloc, previous));
        var cleanup = Instruction.Create(OpCodes.Ldloc, previous); var done = Instruction.Create(OpCodes.Ret);
        foreach (var exit in execute.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray())
        { exit.OpCode = OpCodes.Leave; exit.Operand = done; }
        var il = execute.Body.GetILProcessor();
        il.Append(cleanup); il.Emit(OpCodes.Call, Hook("Exit")); il.Emit(OpCodes.Endfinally); il.Append(done);
        execute.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = original, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        });
        changed.Add(execute);
    }

    // Generic declaring types require an open !0/!1 instantiation even inside
    // their own body. Preserve the actual method/field signature positions.
    private static TypeReference Self(TypeDefinition type)
    {
        if (!type.HasGenericParameters) return type;
        var instance = new GenericInstanceType(type);
        foreach (var parameter in type.GenericParameters) instance.GenericArguments.Add(parameter);
        return instance;
    }

    private static MethodReference Self(MethodDefinition method)
    {
        if (!method.DeclaringType.HasGenericParameters) return method;
        var reference = new MethodReference(method.Name, method.ReturnType, Self(method.DeclaringType)) {
            HasThis = method.HasThis, ExplicitThis = method.ExplicitThis, CallingConvention = method.CallingConvention,
        };
        foreach (var parameter in method.Parameters) reference.Parameters.Add(new ParameterDefinition(parameter.ParameterType));
        return reference;
    }

    private static FieldReference Self(FieldDefinition field) => field.DeclaringType.HasGenericParameters
        ? new FieldReference(field.Name, field.FieldType, Self(field.DeclaringType)) : field;

    private void TaskHooks()
    {
        var task = Type("System.Threading.Tasks.Task");
        var schedule = task.Methods.Single(method => method.Name == "ScheduleAndStart");
        var queue = schedule.Body.Instructions.Single(instruction => instruction.Operand is MethodReference method
            && method.FullName == "System.Void System.Threading.Tasks.TaskScheduler::InternalQueueTask(System.Threading.Tasks.Task)");
        Need(schedule.Body.ExceptionHandlers.Any(handler => handler.CatchType?.FullName == "System.Exception"
            && handler.HandlerStart.OpCode == OpCodes.Newobj
            && handler.HandlerStart.Operand is MethodReference constructor
            && constructor.FullName == "System.Void System.Threading.Tasks.TaskSchedulerException::.ctor(System.Exception)"
            && schedule.Body.Instructions.IndexOf(queue) >= schedule.Body.Instructions.IndexOf(handler.TryStart)
            && schedule.Body.Instructions.IndexOf(queue) < schedule.Body.Instructions.IndexOf(handler.TryEnd)));
        // The scheduler and task arguments already on the IL stack are retained.
        Before(schedule, queue, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("Schedule")));
        changed.Add(schedule);
        var continuation = task.Methods.Single(method => method.Name == "ContinueWithCore");
        Need(continuation.Body.ExceptionHandlers.Count == 0);
        var continuationStart = continuation.Body.Instructions[0];
        Prefix(continuation, "Continuation", Instruction.Create(OpCodes.Ldarg_1));
        var continuationIl = continuation.Body.GetILProcessor();
        var continuationCleanup = Instruction.Create(OpCodes.Ldarg_1); var continuationDone = Instruction.Create(OpCodes.Ret);
        foreach (var exit in continuation.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray())
        { exit.OpCode = OpCodes.Leave; exit.Operand = continuationDone; }
        continuationIl.Append(continuationCleanup); continuationIl.Emit(OpCodes.Call, Hook("ContinuationFailed"));
        continuationIl.Emit(OpCodes.Endfinally); continuationIl.Append(continuationDone);
        continuation.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Fault) {
            TryStart = continuationStart, TryEnd = continuationCleanup, HandlerStart = continuationCleanup, HandlerEnd = continuationDone,
        });

        var finish = task.Methods.Single(method => method.Name == "FinishStageThree");
        var continuations = finish.Body.Instructions.Single(instruction => instruction.Operand is MethodReference method
            && method.FullName == "System.Void System.Threading.Tasks.Task::FinishContinuations()");
        Need(continuations.Next.OpCode == OpCodes.Ret);
        Before(finish, continuations.Next, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("Completed")));
        changed.Add(finish);

        var unwrap = Type("System.Threading.Tasks.UnwrapPromise`1");
        var constructor = unwrap.Methods.Single(method => method.IsConstructor && !method.IsStatic);
        var baseCall = constructor.Body.Instructions.First(instruction => instruction.OpCode == OpCodes.Call
            && instruction.Operand is MethodReference method && method.Name == ".ctor");
        Before(constructor, baseCall.Next, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Ldarg_1),
            Instruction.Create(OpCodes.Call, Hook("Unwrap")));
        changed.Add(constructor);
        Prefix(unwrap.Methods.Single(method => method.Name == "ProcessInnerTask"), "Inner",
            Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Ldarg_1));

        var holder = Type("System.Threading.Tasks.TaskExceptionHolder");
        var handled = holder.Methods.Single(method => method.Name == "MarkAsHandled");
        Prefix(handled, "Observed", Instruction.Create(OpCodes.Ldarg_0),
            Instruction.Create(OpCodes.Ldfld, holder.Fields.Single(field => field.Name == "m_task")));

        // Both the no-context branch and the original captured-context shim call
        // this exact virtual method. Establish ownership inside that real context.
        var invoke = task.Methods.Single(method => method.Name == "InnerInvoke");
        var wrapper = New(task, "LsfInvokeAcceptedWork", module.TypeSystem.Void,
            MethodAttributes.Private | MethodAttributes.Static, task);
        wrapper.Body.InitLocals = true;
        var previous = new VariableDefinition(module.TypeSystem.Object); wrapper.Body.Variables.Add(previous);
        var il = wrapper.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, Hook("Enter")); il.Emit(OpCodes.Stloc, previous);
        var start = Instruction.Create(OpCodes.Ldarg_0); var cleanup = Instruction.Create(OpCodes.Ldloc, previous);
        var done = Instruction.Create(OpCodes.Ret);
        il.Append(start); il.Emit(OpCodes.Callvirt, invoke); il.Emit(OpCodes.Leave, done);
        il.Append(cleanup); il.Emit(OpCodes.Call, Hook("Exit")); il.Emit(OpCodes.Endfinally); il.Append(done);
        wrapper.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = start, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        });
        int sites = 0;
        foreach (var method in module.GetTypes().Where(type => type == task || type.DeclaringType == task)
            .SelectMany(type => type.Methods).Where(method => method.HasBody && method != wrapper))
            foreach (var instruction in method.Body.Instructions)
                if (instruction.OpCode == OpCodes.Callvirt && instruction.Operand is MethodReference reference && reference.Resolve() == invoke)
                {
                    instruction.OpCode = OpCodes.Call; instruction.Operand = wrapper; changed.Add(method); sites++;
                }
        Need(sites == 2);

        var builder = Type("System.Runtime.CompilerServices.AsyncTaskMethodBuilder`1");
        var stateMachine = builder.Methods.Single(method => method.Name == "GetStateMachineBox");
        Need(stateMachine.IsPrivate && stateMachine.IsStatic && stateMachine.GenericParameters.Count == 1
            && stateMachine.Parameters.Count == 2 && stateMachine.Parameters.All(parameter => parameter.ParameterType is ByReferenceType)
            && stateMachine.ReturnType.FullName == "System.Runtime.CompilerServices.IAsyncStateMachineBox");
        var returns = stateMachine.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray();
        Need(returns.Length == 1);
        Before(stateMachine, returns[0], Instruction.Create(OpCodes.Dup), Instruction.Create(OpCodes.Castclass, task),
            Instruction.Create(OpCodes.Call, Hook("CreatedAsync")));
        changed.Add(stateMachine);
    }

    private void QueueHooks()
    {
        var queue = Type("System.Threading.ThreadPoolWorkQueue");
        var enqueue = queue.Methods.Single(method => method.Name == "Enqueue" && method.Parameters.Count == 2);
        Need(!enqueue.IsStatic && enqueue.ReturnType.MetadataType == MetadataType.Void
            && enqueue.Parameters[0].ParameterType.MetadataType == MetadataType.Object
            && enqueue.Body.ExceptionHandlers.Count == 0);
        var relocate = New(queue, "LsfRelocateAcceptedWork", module.TypeSystem.Void,
            MethodAttributes.Assembly, module.TypeSystem.Object, module.TypeSystem.Boolean);
        CloneBody(enqueue, relocate);
        var transfer = Type("System.Threading.ThreadPoolWorkQueueThreadLocals").Methods.Single(method => method.Name == "TransferLocalWork");
        var move = transfer.Body.Instructions.Single(instruction => instruction.Operand is MethodReference method && method.Resolve() == enqueue);
        move.Operand = relocate; changed.Add(transfer);

        QueueAdmission(enqueue);
        QueueAdmission(queue.Methods.Single(method => method.Name == "EnqueueAtHighPriority" && method.Parameters.Count == 1));
        var pop = queue.Methods.Single(method => method.Name == "LocalFindAndPop");
        Need(pop.IsStatic && pop.Parameters.Count == 1 && pop.ReturnType.MetadataType == MetadataType.Boolean);
        foreach (var exit in pop.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray())
            Before(pop, exit, Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("Popped")));
        changed.Add(pop);

        var dispatch = queue.Methods.Single(method => method.Name == "DispatchWorkItem");
        Need(dispatch.IsStatic && dispatch.Parameters.Count == 2 && dispatch.Parameters[0].ParameterType.MetadataType == MetadataType.Object);
        // A callback's logical completion is published only after its original
        // Execute path (including its finally) has returned or thrown.
        var originalStart = dispatch.Body.Instructions[0];
        var previous = new VariableDefinition(module.TypeSystem.Object);
        dispatch.Body.InitLocals = true; dispatch.Body.Variables.Add(previous);
        var il = dispatch.Body.GetILProcessor();
        // Ledger/context refusals precede the original user exception handler;
        // no global user handler may swallow failed bookkeeping as success.
        foreach (var instruction in new[] { Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("Dequeue")),
            Instruction.Create(OpCodes.Ldarg_0), Instruction.Create(OpCodes.Call, Hook("EnterDispatch")),
            Instruction.Create(OpCodes.Stloc, previous) }) il.InsertBefore(originalStart, instruction);
        var exits = dispatch.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray();
        var cleanup = Instruction.Create(OpCodes.Ldloc, previous); var done = Instruction.Create(OpCodes.Ret);
        foreach (var exit in exits) { exit.OpCode = OpCodes.Leave; exit.Operand = done; }
        // Existing open handler ends must terminate before the new outer finally.
        foreach (var handler in dispatch.Body.ExceptionHandlers)
        {
            if (handler.TryEnd is null) handler.TryEnd = cleanup;
            if (handler.HandlerEnd is null) handler.HandlerEnd = cleanup;
        }
        il.Append(cleanup); il.Emit(OpCodes.Call, Hook("Exit"));
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, Hook("CallbackCompleted")); il.Emit(OpCodes.Endfinally); il.Append(done);
        dispatch.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = originalStart, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        });
        changed.Add(dispatch);
    }

    private static void CloneBody(MethodDefinition original, MethodDefinition copied)
    {
        Need(original.Module == copied.Module && original.Body.ExceptionHandlers.Count == 0);
        copied.Body.InitLocals = original.Body.InitLocals; copied.Body.MaxStackSize = original.Body.MaxStackSize;
        var variables = new Dictionary<VariableDefinition, VariableDefinition>();
        foreach (var variable in original.Body.Variables)
        {
            var selected = new VariableDefinition(variable.VariableType);
            variables.Add(variable, selected); copied.Body.Variables.Add(selected);
        }
        var instructions = original.Body.Instructions.ToDictionary(instruction => instruction, _ => Instruction.Create(OpCodes.Nop));
        foreach (var instruction in original.Body.Instructions)
        {
            var selected = instructions[instruction]; selected.OpCode = instruction.OpCode;
            selected.Operand = instruction.Operand switch {
                Instruction branch => instructions[branch], Instruction[] branches => branches.Select(branch => instructions[branch]).ToArray(),
                VariableDefinition variable => variables[variable], ParameterDefinition parameter => copied.Parameters[parameter.Index],
                null or MethodReference or FieldReference or TypeReference or string or sbyte or byte or int or long or float or double => instruction.Operand,
                _ => throw new InvalidDataException("managed-work-relocation-body"),
            };
            copied.Body.Instructions.Add(selected);
        }
    }

    private void QueueAdmission(MethodDefinition enqueue)
    {
        Need(!enqueue.IsStatic && enqueue.ReturnType.MetadataType == MetadataType.Void
            && enqueue.Parameters[0].ParameterType.MetadataType == MetadataType.Object && enqueue.Body.ExceptionHandlers.Count == 0);
        var il = enqueue.Body.GetILProcessor();
        var start = enqueue.Body.Instructions[0];
        Before(enqueue, start, Instruction.Create(OpCodes.Ldarg_1), Instruction.Create(OpCodes.Call, Hook("Enqueue")));
        var exits = enqueue.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray();
        var cleanup = Instruction.Create(OpCodes.Ldarg_1); var done = Instruction.Create(OpCodes.Ret);
        foreach (var exit in exits) { exit.OpCode = OpCodes.Leave; exit.Operand = done; }
        il.Append(cleanup); il.Emit(OpCodes.Call, Hook("EnqueueFailed")); il.Emit(OpCodes.Endfinally); il.Append(done);
        enqueue.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Fault) {
            TryStart = start, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        });
        changed.Add(enqueue);
    }

    // Evaluate only the actual generated accessor's five read-only opcodes.
    // This is a compiler metadata control, not guest or CLR runtime qualification.
    private static void CheckPrefetchedReadiness(MethodDefinition method,
        FieldDefinition workQueue, FieldDefinition prefetched)
    {
        Need(method.Body.Instructions.Count == 5);
        var queue = new object();
        bool Read(object? slot)
        {
            var stack = new Stack<object?>();
            foreach (var instruction in method.Body.Instructions)
                switch (instruction.OpCode.Code)
                {
                    case Code.Ldsfld:
                        Need(ReferenceEquals(instruction.Operand, workQueue)); stack.Push(queue); break;
                    case Code.Ldfld:
                        Need(ReferenceEquals(instruction.Operand, prefetched)
                            && ReferenceEquals(stack.Pop(), queue)); stack.Push(slot); break;
                    case Code.Ldnull: stack.Push(null); break;
                    case Code.Cgt_Un:
                        var right = stack.Pop(); stack.Push(!ReferenceEquals(stack.Pop(), right)); break;
                    case Code.Ret:
                        Need(stack.Count == 1 && stack.Peek() is bool); return (bool)stack.Pop()!;
                    default: throw new InvalidDataException("managed-work-prefetched-readiness-opcode");
                }
            throw new InvalidDataException("managed-work-prefetched-readiness-return");
        }
        foreach (bool queued in new[] { false, true })
            foreach (object? slot in new object?[] { null, new object() })
            {
                bool original = queued;
                bool actual = Read(slot) || queued;
                Need(actual == (queued || slot is not null)
                    && (slot is not null || actual == original));
                if (!queued && slot is not null) Need(!original && actual);
            }
    }

    private void ProducerBindings()
    {
        var loop = Type("System.Threading.WasiEventLoop");
        var schedule = loop.Methods.Single(method => method.Name == "ScheduleCheck");
        var cache = schedule.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ldsfld
            && instruction.Operand is FieldReference field && field.FieldType.FullName == "System.Threading.WaitCallback")
            .Select(instruction => ((FieldReference)instruction.Operand).Resolve()).Single();
        Need(cache.IsStatic && cache.DeclaringType.DeclaringType == loop
            && schedule.Body.Instructions.Count(instruction => instruction.OpCode == OpCodes.Ldftn
                && instruction.Operand is MethodReference method && method.FullName ==
                    "System.Void System.Threading.WasiEventLoop::CheckPollables(System.Object)") == 1);
        var cached = New(loop, "LsfPollDriverDelegate", cache.FieldType,
            MethodAttributes.Assembly | MethodAttributes.Static);
        var il = cached.Body.GetILProcessor();
        il.Emit(OpCodes.Ldsfld, cache); il.Emit(OpCodes.Ret);
        var predicates = new List<MethodDefinition>();
        foreach (string name in new[] { "System.Threading.QueueUserWorkItemCallback", "System.Threading.QueueUserWorkItemCallbackDefaultContext" })
        {
            var type = Type(name);
            var callback = type.Fields.Single(field => field.Name == "_callback");
            var state = type.Fields.Single(field => field.Name == "_state");
            var predicate = New(type, "LsfIsPollDriver", module.TypeSystem.Boolean,
                MethodAttributes.Assembly | MethodAttributes.Static, module.TypeSystem.Object);
            predicate.Body.InitLocals = true;
            var item = new VariableDefinition(type); predicate.Body.Variables.Add(item);
            il = predicate.Body.GetILProcessor(); var no = Instruction.Create(OpCodes.Ldc_I4_0);
            il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Isinst, type); il.Emit(OpCodes.Stloc, item);
            il.Emit(OpCodes.Ldloc, item); il.Emit(OpCodes.Brfalse, no);
            il.Emit(OpCodes.Ldloc, item); il.Emit(OpCodes.Ldfld, state); il.Emit(OpCodes.Brtrue, no);
            il.Emit(OpCodes.Ldloc, item); il.Emit(OpCodes.Ldfld, callback); il.Emit(OpCodes.Dup);
            var valid = Instruction.Create(OpCodes.Call, cached);
            il.Emit(OpCodes.Brtrue, valid); il.Emit(OpCodes.Pop); il.Emit(OpCodes.Br, no);
            il.Append(valid); il.Emit(OpCodes.Ceq); il.Emit(OpCodes.Ret); il.Append(no); il.Emit(OpCodes.Ret);
            predicates.Add(predicate);
        }
        var maintenance = Hook("Maintenance"); maintenance.Body = new MethodBody(maintenance);
        il = maintenance.Body.GetILProcessor(); var yes = Instruction.Create(OpCodes.Ldc_I4_1);
        foreach (var predicate in predicates)
        { il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, predicate); il.Emit(OpCodes.Brtrue, yes); }
        il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Ret); il.Append(yes); il.Emit(OpCodes.Ret);

        var continuation = Hook("RequiredContinuation"); continuation.Body = new MethodBody(continuation);
        il = continuation.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Isinst, Type("System.Runtime.CompilerServices.IAsyncStateMachineBox"));
        il.Emit(OpCodes.Ldnull); il.Emit(OpCodes.Cgt_Un); il.Emit(OpCodes.Ret);

        // The dispatcher can retain an eligible item outside every counted queue.
        // Read its original slot without consuming it or creating another owner.
        var queue = Type("System.Threading.ThreadPoolWorkQueue");
        var workQueue = Type("System.Threading.ThreadPool").Fields.Single(field => field.Name == "s_workQueue");
        var prefetched = queue.Fields.Single(field => field.Name == "_nextWorkItemToProcess");
        Need(workQueue.IsStatic && (workQueue.IsAssembly || workQueue.IsPublic)
            && workQueue.FieldType.FullName == queue.FullName
            && prefetched.IsPrivate && !prefetched.IsStatic
            && prefetched.FieldType.MetadataType == MetadataType.Object
            && queue.Methods.Single(method => method.Name == "Dispatch").Body.Instructions.Any(instruction =>
                instruction.Operand is FieldReference field && field.Resolve() == prefetched));
        var prefetchedReady = New(queue, "LsfManagedWorkPrefetchedReady", module.TypeSystem.Boolean,
            MethodAttributes.Assembly | MethodAttributes.Static);
        il = prefetchedReady.Body.GetILProcessor();
        il.Emit(OpCodes.Ldsfld, workQueue); il.Emit(OpCodes.Ldfld, prefetched);
        il.Emit(OpCodes.Ldnull); il.Emit(OpCodes.Cgt_Un); il.Emit(OpCodes.Ret);
        CheckPrefetchedReadiness(prefetchedReady, workQueue, prefetched);

        var ready = New(loop, "LsfManagedWorkReady", module.TypeSystem.Boolean,
            MethodAttributes.Assembly | MethodAttributes.Static);
        il = ready.Body.GetILProcessor(); yes = Instruction.Create(OpCodes.Ldc_I4_1);
        foreach (string fieldName in new[] { "s_pollables", "s_hooks" })
        {
            var field = loop.Fields.Single(candidate => candidate.Name == fieldName);
            var count = schedule.Body.Instructions.Select(instruction => instruction.Operand).OfType<MethodReference>()
                .Single(method => method.Name == "get_Count" && method.DeclaringType.FullName == field.FieldType.FullName);
            il.Emit(OpCodes.Ldsfld, field); il.Emit(OpCodes.Callvirt, count); il.Emit(OpCodes.Brtrue, yes);
        }
        il.Emit(OpCodes.Call, prefetchedReady); il.Emit(OpCodes.Brtrue, yes);
        il.Emit(OpCodes.Call, Type("System.Threading.ThreadPool").Methods.Single(method => method.Name == "get_PendingWorkItemCount"));
        il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Cgt); il.Emit(OpCodes.Ret);
        il.Append(yes); il.Emit(OpCodes.Ret);
        var readyStub = Hook("ReadySource"); readyStub.Body = new MethodBody(readyStub);
        il = readyStub.Body.GetILProcessor(); il.Emit(OpCodes.Call, ready); il.Emit(OpCodes.Ret);
    }

    private void TimerHooks(IReadOnlyDictionary<string, string> originalBodies)
    {
        var queue = Type("System.Threading.TimerQueue");
        var timer = Type("System.Threading.TimerQueueTimer");
        MethodDefinition Original(TypeDefinition type, string name, int parameters, string expected)
        {
            var method = type.Methods.Single(candidate => candidate.Name == name && candidate.Parameters.Count == parameters);
            string key = type.FullName + "#" + type.Methods.IndexOf(method);
            Need(originalBodies[key] == expected);
            return method;
        }
        var update = Original(queue, "UpdateTimer", 3, "a6718748ddf98afce1b550bd346cf0140de8944544f600816362c15b61fd4b6b");
        var deleted = Original(queue, "DeleteTimer", 1, "97df4a648d3a936be0a512e16dff243bee88b9b77a44c5865e8c6f3f0d4f2f8d");
        var accepted = Original(queue, "FireNextTimers", 0, "5e78e327e830b1b1543c560634848e2244663e3ec32686f5d6f8bd7904a11f09");
        var fire = Original(timer, "Fire", 1, "7aac3cfdb1d33f5f32c3ef6760cc61596a805b5e33a26cee5d07ced09ec8962b");
        var callback = Original(timer, "CallCallback", 1, "078f485b1d05ad88167bae8b04cb7c683ccb6987620d2b433507ec9c52e3097d");
        Need(update.Body.ExceptionHandlers.Count == 0 && update.ReturnType.MetadataType == MetadataType.Boolean
            && accepted.Body.Instructions.Count(instruction => instruction.Operand is FieldReference field
                && field.Name == "_everQueued") == 1);
        // Other existing compiler ports only touch DeleteTimer; these four
        // producer bodies must still equal their exact authenticated preimages.
        foreach (var method in new[] { update, accepted, fire, callback })
            Need(TaskWait.BodyIdentity(method) == originalBodies[method.DeclaringType.FullName + "#" + method.DeclaringType.Methods.IndexOf(method)]);

        foreach (var (stub, fieldName, result) in new[] {
            ("TimerScheduled", "_dueTime", module.TypeSystem.Boolean),
            ("TimerCallbacks", "_callbacksRunning", module.TypeSystem.Int32) })
        {
            var field = timer.Fields.Single(candidate => candidate.Name == fieldName);
            Need((fieldName == "_dueTime" ? field.IsAssembly : field.IsPrivate)
                && !field.IsStatic && field.FieldType.MetadataType ==
                (fieldName == "_dueTime" ? MetadataType.UInt32 : MetadataType.Int32));
            var reader = New(timer, "Lsf" + stub, result,
                MethodAttributes.Assembly | MethodAttributes.Static, module.TypeSystem.Object);
            var code = reader.Body.GetILProcessor();
            code.Emit(OpCodes.Ldarg_0); code.Emit(OpCodes.Castclass, timer); code.Emit(OpCodes.Ldfld, field);
            if (fieldName == "_dueTime")
            { code.Emit(OpCodes.Ldc_I4_M1); code.Emit(OpCodes.Ceq); code.Emit(OpCodes.Ldc_I4_0); code.Emit(OpCodes.Ceq); }
            code.Emit(OpCodes.Ret);
            var target = Hook(stub); target.Body = new MethodBody(target);
            code = target.Body.GetILProcessor(); code.Emit(OpCodes.Ldarg_0); code.Emit(OpCodes.Call, reader); code.Emit(OpCodes.Ret);
        }

        // Admission precedes all original list/active-count mutation. The outer
        // finally checks real original state after successful or failed Change.
        var original = update.Body.Instructions[0];
        var il = update.Body.GetILProcessor();
        il.InsertBefore(original, Instruction.Create(OpCodes.Ldarg_1));
        il.InsertBefore(original, Instruction.Create(OpCodes.Call, Hook("TimerChanging")));
        var resultValue = new VariableDefinition(module.TypeSystem.Boolean);
        update.Body.InitLocals = true; update.Body.Variables.Add(resultValue);
        var cleanup = Instruction.Create(OpCodes.Ldarg_1); var done = Instruction.Create(OpCodes.Ldloc, resultValue);
        foreach (var exit in update.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray())
        {
            exit.OpCode = OpCodes.Stloc; exit.Operand = resultValue;
            il.InsertAfter(exit, Instruction.Create(OpCodes.Leave, done));
        }
        il.Append(cleanup); il.Emit(OpCodes.Call, Hook("TimerChanged")); il.Emit(OpCodes.Endfinally);
        il.Append(done); il.Emit(OpCodes.Ret);
        update.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = original, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        }); changed.Add(update);

        var exitDelete = deleted.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Ret);
        Before(deleted, exitDelete, Instruction.Create(OpCodes.Ldarg_1), Instruction.Create(OpCodes.Call, Hook("TimerDeleted")));
        changed.Add(deleted);
        var queued = accepted.Body.Instructions.Single(instruction => instruction.Operand is FieldReference field && field.Name == "_everQueued");
        Need(queued.OpCode == OpCodes.Stfld && queued.Previous.OpCode == OpCodes.Ldc_I4_1);
        // Stack is [actual timer] here. Preserve its original true/store pair.
        Before(accepted, queued.Previous, Instruction.Create(OpCodes.Dup), Instruction.Create(OpCodes.Call, Hook("TimerAccepted")));
        changed.Add(accepted);

        original = fire.Body.Instructions[0]; il = fire.Body.GetILProcessor();
        var previous = new VariableDefinition(module.TypeSystem.Object);
        fire.Body.InitLocals = true; fire.Body.Variables.Add(previous);
        il.InsertBefore(original, Instruction.Create(OpCodes.Ldarg_0));
        il.InsertBefore(original, Instruction.Create(OpCodes.Call, Hook("TimerEnter")));
        il.InsertBefore(original, Instruction.Create(OpCodes.Stloc, previous));
        cleanup = Instruction.Create(OpCodes.Ldarg_0); done = Instruction.Create(OpCodes.Ret);
        foreach (var exit in fire.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Ret).ToArray())
        { exit.OpCode = OpCodes.Leave; exit.Operand = done; }
        il.Append(cleanup); il.Emit(OpCodes.Ldloc, previous); il.Emit(OpCodes.Call, Hook("TimerLeave")); il.Emit(OpCodes.Endfinally); il.Append(done);
        fire.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = original, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = done,
        }); changed.Add(fire);

        var captured = callback.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Ldfld
            && instruction.Operand is FieldReference field && field.Name == "_executionContext");
        il = callback.Body.GetILProcessor(); var item = Instruction.Create(OpCodes.Ldarg_0);
        il.InsertAfter(captured, item); il.InsertAfter(item, Instruction.Create(OpCodes.Call, Hook("BindContext")));
        changed.Add(callback);
    }

    private void BridgeBindings()
    {
        var task = Type("System.Threading.Tasks.Task");
        foreach (var (name, hook) in new[] { ("LsfInstallAcceptedWork", "Install"),
            ("LsfJoinAcceptedWork", "JoinAcceptedWork"), ("LsfFinishAcceptedWork", "FinishedPhysicalDrain") })
        {
            var target = Hook(hook);
            var method = New(task, name, target.ReturnType, MethodAttributes.Private | MethodAttributes.Static,
                target.Parameters.Select(parameter => parameter.ParameterType).ToArray());
            var il = method.Body.GetILProcessor();
            foreach (var parameter in method.Parameters) il.Emit(OpCodes.Ldarg, parameter);
            il.Emit(OpCodes.Call, target); il.Emit(OpCodes.Ret);
        }
        var loop = Type("System.Threading.WasiEventLoop");
        var wait = loop.Methods.Single(method => method.Name == "LsfWaitForActualTaskCompletion");
        Need(wait.IsStatic && wait.ReturnType.MetadataType == MetadataType.Boolean
            && wait.Parameters.Count == 1 && wait.Parameters[0].ParameterType.FullName == task.FullName);
        // Cross-type call only; this newly generated helper was private in v1.
        wait.Attributes = (wait.Attributes & ~MethodAttributes.MemberAccessMask) | MethodAttributes.Assembly;
        var waitStub = Hook("WaitForCompletion"); waitStub.Body = new MethodBody(waitStub);
        var code = waitStub.Body.GetILProcessor();
        code.Emit(OpCodes.Ldarg_0); code.Emit(OpCodes.Call, wait); code.Emit(OpCodes.Pop); code.Emit(OpCodes.Ret);

        var queue = Type("System.Threading.ThreadPoolWorkQueue");
        var dispatch = queue.Methods.Single(method => method.Name == "Dispatch");
        var waitPump = loop.Methods.Single(method => method.Name == "LsfDispatchUntilActualTaskCompletion");
        var step = waitPump.Body.Instructions.Single(instruction => instruction.Operand is MethodReference method
            && method.Resolve() == dispatch);
        Before(waitPump, step, Instruction.Create(OpCodes.Call, Hook("EnsureJoinReady")));
        var callback = Type("System.Threading.ContextCallback");
        var constructor = callback.Methods.Single(method => method.IsConstructor && method.Parameters.Count == 2);
        var body = New(loop, "LsfManagedWorkDispatchBody", module.TypeSystem.Void,
            MethodAttributes.Private | MethodAttributes.Static, module.TypeSystem.Object);
        code = body.Body.GetILProcessor(); code.Emit(OpCodes.Call, dispatch); code.Emit(OpCodes.Pop); code.Emit(OpCodes.Ret);
        var once = New(loop, "LsfManagedWorkDispatchOnce", module.TypeSystem.Void,
            MethodAttributes.Assembly | MethodAttributes.Static);
        code = once.Body.GetILProcessor();
        var context = Type("System.Threading.ExecutionContext");
        code.Emit(OpCodes.Ldsfld, context.Fields.Single(field => field.Name == "Default"));
        code.Emit(OpCodes.Ldnull); code.Emit(OpCodes.Ldftn, body); code.Emit(OpCodes.Newobj, constructor);
        code.Emit(OpCodes.Ldnull); code.Emit(OpCodes.Call, context.Methods.Single(method => method.Name == "RunInternal"));
        code.Emit(OpCodes.Ret);
        var dispatchStub = Hook("DispatchOnce"); dispatchStub.Body = new MethodBody(dispatchStub);
        code = dispatchStub.Body.GetILProcessor(); code.Emit(OpCodes.Call, once); code.Emit(OpCodes.Ret);
    }

    internal static void Widen(MethodDefinition method)
    {
        foreach (var instruction in method.Body.Instructions)
            instruction.OpCode = instruction.OpCode.Code switch {
                Code.Br_S => OpCodes.Br, Code.Brfalse_S => OpCodes.Brfalse, Code.Brtrue_S => OpCodes.Brtrue,
                Code.Beq_S => OpCodes.Beq, Code.Bge_S => OpCodes.Bge, Code.Bge_Un_S => OpCodes.Bge_Un,
                Code.Bgt_S => OpCodes.Bgt, Code.Bgt_Un_S => OpCodes.Bgt_Un, Code.Ble_S => OpCodes.Ble,
                Code.Ble_Un_S => OpCodes.Ble_Un, Code.Blt_S => OpCodes.Blt, Code.Blt_Un_S => OpCodes.Blt_Un,
                Code.Bne_Un_S => OpCodes.Bne_Un, Code.Leave_S => OpCodes.Leave, _ => instruction.OpCode,
            };
        method.Body.MaxStackSize = Math.Max(method.Body.MaxStackSize + 2, 8);
    }

    internal (MethodDefinition[] Changed, MethodDefinition[] Added) Install(IReadOnlyDictionary<string, string> originalBodies)
    {
        CapturedContext(); TaskHooks(); QueueHooks(); ProducerBindings(); TimerHooks(originalBodies); BridgeBindings();
        foreach (var method in changed) Widen(method);
        return (changed.ToArray(), added.ToArray());
    }
}

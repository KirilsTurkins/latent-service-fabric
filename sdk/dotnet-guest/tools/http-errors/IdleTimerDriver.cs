using Mono.Cecil;
using Mono.Cecil.Cil;

// Called only after TaskWait authenticates the complete original WASI CoreLib.
// The private token belongs solely to TimerQueue's platform driver registrations.
internal static class IdleTimerDriver
{
    private static void Require(bool value)
    {
        if (!value) throw new InvalidDataException("task-wait-idle-driver-shape");
    }

    internal static MethodDefinition[] Install(ModuleDefinition module)
    {
        TypeDefinition Type(string name) => module.GetTypes().Single(type => type.FullName == name);
        var queue = Type("System.Threading.TimerQueue");
        var task = Type("System.Threading.Tasks.Task");
        var timer = Type("System.Threading.Timer");
        var ctsType = Type("System.Threading.CancellationTokenSource");
        var tokenType = Type("System.Threading.CancellationToken");
        var scheduler = Type("System.Threading.Tasks.TaskScheduler");
        var context = Type("System.Threading.ExecutionContext");
        var flowType = Type("System.Threading.AsyncFlowControl");
        var flowSuppressed = context.Methods.Single(method => method.Name == "IsFlowSuppressed" && method.Parameters.Count == 0);
        var suppressFlow = context.Methods.Single(method => method.Name == "SuppressFlow" && method.Parameters.Count == 0);
        var undoFlow = flowType.Methods.Single(method => method.Name == "Undo" && method.Parameters.Count == 0);
        var set = queue.Methods.Single(method => method.Name == "SetNextTimer");
        var handler = queue.Methods.Single(method => method.Name == "TimerHandler");
        var delete = queue.Methods.Single(method => method.Name == "DeleteTimer");
        var pump = queue.Methods.Single(method => method.Name == "PumpTimerQueue");
        var active = timer.Methods.Single(method => method.Name == "get_ActiveCount");
        var instances = queue.Methods.Single(method => method.Name == "get_Instances");
        var scheduled = queue.Fields.Single(field => field.Name == "s_scheduledTimers");
        var toFire = queue.Fields.Single(field => field.Name == "s_scheduledTimersToFire");
        var shortest = queue.Fields.Single(field => field.Name == "s_shortestDueTimeMs");
        var armed = queue.Fields.Single(field => field.Name == "_isTimerScheduled");
        var inList = queue.Fields.Single(field => field.Name == "_isScheduled");
        var due = queue.Fields.Single(field => field.Name == "_scheduledDueTimeMs");
        Require(set.IsStatic && set.ReturnType.MetadataType == MetadataType.Void && set.Parameters.Count == 2 &&
            set.Parameters.All(parameter => parameter.ParameterType.MetadataType == MetadataType.Int64) &&
            handler.IsStatic && handler.ReturnType.MetadataType == MetadataType.Void && handler.Parameters.Count == 1 &&
            handler.Parameters[0].ParameterType.MetadataType == MetadataType.Object &&
            !delete.IsStatic && delete.ReturnType.MetadataType == MetadataType.Void && delete.Parameters.Count == 1 &&
            delete.Parameters[0].ParameterType.FullName == "System.Threading.TimerQueueTimer" &&
            active.IsStatic && active.ReturnType.MetadataType == MetadataType.Int64 && active.Parameters.Count == 0 &&
            instances.IsStatic && instances.Parameters.Count == 0 && instances.ReturnType is ArrayType array &&
            array.ElementType.FullName == queue.FullName && shortest.IsStatic &&
            shortest.FieldType.MetadataType == MetadataType.Int64 && !armed.IsStatic && !inList.IsStatic && !due.IsStatic &&
            armed.FieldType.MetadataType == MetadataType.Boolean && inList.FieldType.MetadataType == MetadataType.Boolean &&
            due.FieldType.MetadataType == MetadataType.Int64 && scheduled.IsStatic && toFire.IsStatic &&
            scheduled.FieldType is GenericInstanceType list && list.ElementType.FullName == "System.Collections.Generic.List`1" &&
            list.GenericArguments.Count == 1 && list.GenericArguments[0].FullName == queue.FullName &&
            toFire.FieldType.FullName == scheduled.FieldType.FullName &&
            !queue.Fields.Any(field => field.Name.StartsWith("s_lsfTimerDriver", StringComparison.Ordinal)) &&
            !queue.Methods.Any(method => method.Name.StartsWith("LsfTimerDriver", StringComparison.Ordinal)) &&
            !queue.NestedTypes.Any(type => type.Name == "LsfTimerDriverState"));
        Require(flowSuppressed.IsStatic && flowSuppressed.ReturnType.MetadataType == MetadataType.Boolean &&
            suppressFlow.IsStatic && suppressFlow.ReturnType.FullName == flowType.FullName &&
            !undoFlow.IsStatic && undoFlow.ReturnType.MetadataType == MetadataType.Void);
        MethodReference Call(MethodDefinition method, string name) => method.Body.Instructions
            .Where(instruction => instruction.Operand is MethodReference reference && reference.Name == name)
            .Select(instruction => (MethodReference)instruction.Operand).Single();
        var subscribe = Call(set, "SubscribeDuration");
        var register = Call(set, "RegisterWasiPollable");
        var maximum = Call(set, "Max");
        var none = Call(set, "get_None");
        var defaultScheduler = Call(set, "get_Default");
        Require(subscribe.Parameters.Count == 1 && subscribe.Parameters[0].ParameterType.MetadataType == MetadataType.UInt64 &&
            register.DeclaringType.FullName == "System.Threading.WasiEventLoop" && register.Parameters.Count == 3 &&
            register.Parameters[0].ParameterType.FullName == subscribe.ReturnType.FullName &&
            register.Parameters[1].ParameterType.MetadataType == MetadataType.Boolean &&
            register.Parameters[2].ParameterType.FullName == tokenType.FullName && register.ReturnType.FullName == task.FullName &&
            maximum.FullName == "System.Int64 System.Math::Max(System.Int64,System.Int64)" &&
            none.DeclaringType.FullName == tokenType.FullName && none.ReturnType.FullName == tokenType.FullName &&
            defaultScheduler.DeclaringType.FullName == scheduler.FullName &&
            handler.Body.Instructions.Count(instruction => instruction.Operand is MethodReference reference && reference.FullName == set.FullName) == 1 &&
            handler.Body.Instructions.Count(instruction => instruction.Operand is MethodReference reference && reference.FullName == pump.FullName) == 1 &&
            delete.Body.Instructions.Count(instruction => instruction.OpCode == OpCodes.Ret) == 1);
        var ctsConstructor = ctsType.Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0);
        var getToken = ctsType.Methods.Single(method => method.Name == "get_Token" && method.Parameters.Count == 0);
        var cancel = ctsType.Methods.Single(method => method.Name == "Cancel" && method.Parameters.Count == 0);
        var dispose = ctsType.Methods.Single(method => method.Name == "Dispose" && method.Parameters.Count == 0);
        var cancelled = task.Methods.Single(method => method.Name == "get_IsCanceled");
        var succeeded = task.Methods.Single(method => method.Name == "get_IsCompletedSuccessfully");
        var referenceEquals = Type("System.Object").Methods.Single(method => method.Name == "ReferenceEquals");
        var invalid = Type("System.InvalidOperationException").Methods.Single(method => method.IsConstructor &&
            method.Parameters.Count == 1 && method.Parameters[0].ParameterType.MetadataType == MetadataType.String);
        var action = new GenericInstanceType(Type("System.Action`2"));
        action.GenericArguments.Add(task); action.GenericArguments.Add(module.TypeSystem.Object);
        var continueWith = task.Methods.Single(method => method.Name == "ContinueWith" && method.Parameters.Count == 3 &&
            method.Parameters[0].ParameterType.FullName == action.FullName &&
            method.Parameters[1].ParameterType.MetadataType == MetadataType.Object && method.Parameters[2].ParameterType.FullName == scheduler.FullName);
        var actionConstructor = new MethodReference(".ctor", module.TypeSystem.Void, action) { HasThis = true };
        actionConstructor.Parameters.Add(new ParameterDefinition(module.TypeSystem.Object));
        actionConstructor.Parameters.Add(new ParameterDefinition(module.TypeSystem.IntPtr));
        var clear = new MethodReference("Clear", module.TypeSystem.Void, scheduled.FieldType) { HasThis = true };
        var source = new FieldDefinition("s_lsfTimerDriverCancellation", FieldAttributes.Private | FieldAttributes.Static, ctsType);
        var epoch = new FieldDefinition("s_lsfTimerDriverEpoch", FieldAttributes.Private | FieldAttributes.Static, module.TypeSystem.Int64);
        queue.Fields.Add(source); queue.Fields.Add(epoch);
        MethodDefinition Method(string name, TypeReference result, params TypeReference[] parameters)
        {
            var method = new MethodDefinition(name, MethodAttributes.Private | MethodAttributes.Static | MethodAttributes.HideBySig, result);
            foreach (var parameter in parameters) method.Parameters.Add(new ParameterDefinition(parameter));
            method.Body.InitLocals = true; method.Body.MaxStackSize = 8; queue.Methods.Add(method); return method;
        }
        var token = Method("LsfTimerDriverToken", tokenType);
        var registration = Method("LsfTimerDriverRegister", task, subscribe.ReturnType, module.TypeSystem.Boolean, tokenType);
        var callback = Method("LsfTimerDriverCallback", module.TypeSystem.Void, task, module.TypeSystem.Object);
        var rearm = Method("LsfTimerDriverRearm", module.TypeSystem.Void, module.TypeSystem.Int64, module.TypeSystem.Int64, module.TypeSystem.Int64);
        var retire = Method("LsfTimerDriverRetireIfIdle", module.TypeSystem.Void);
        var state = new TypeDefinition("", "LsfTimerDriverState", TypeAttributes.NestedPrivate | TypeAttributes.Sealed | TypeAttributes.BeforeFieldInit, module.TypeSystem.Object);
        queue.NestedTypes.Add(state);
        var stateTask = new FieldDefinition("Task", FieldAttributes.Assembly | FieldAttributes.InitOnly, task);
        var stateEpoch = new FieldDefinition("Epoch", FieldAttributes.Assembly | FieldAttributes.InitOnly, module.TypeSystem.Int64);
        state.Fields.Add(stateTask); state.Fields.Add(stateEpoch);
        var stateConstructor = new MethodDefinition(".ctor", MethodAttributes.Assembly | MethodAttributes.HideBySig | MethodAttributes.SpecialName | MethodAttributes.RTSpecialName, module.TypeSystem.Void);
        stateConstructor.Parameters.Add(new ParameterDefinition(task)); stateConstructor.Parameters.Add(new ParameterDefinition(module.TypeSystem.Int64));
        state.Methods.Add(stateConstructor);
        var ctor = stateConstructor.Body.GetILProcessor();
        ctor.Emit(OpCodes.Ldarg_0); ctor.Emit(OpCodes.Call, Type("System.Object").Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0));
        ctor.Emit(OpCodes.Ldarg_0); ctor.Emit(OpCodes.Ldarg_1); ctor.Emit(OpCodes.Stfld, stateTask);
        ctor.Emit(OpCodes.Ldarg_0); ctor.Emit(OpCodes.Ldarg_2); ctor.Emit(OpCodes.Stfld, stateEpoch); ctor.Emit(OpCodes.Ret);

        var il = token.Body.GetILProcessor(); var exists = il.Create(OpCodes.Ldsfld, source);
        il.Emit(OpCodes.Ldsfld, source); il.Emit(OpCodes.Brtrue, exists); il.Emit(OpCodes.Newobj, ctsConstructor); il.Emit(OpCodes.Stsfld, source);
        il.Append(exists); il.Emit(OpCodes.Callvirt, getToken); il.Emit(OpCodes.Ret);

        // CancellationToken.None did not capture ExecutionContext. Avoid adding
        // a captured context only for this new private driver cancellation edge.
        // Return with the original flow state before the original ContinueWith.
        var flow = new VariableDefinition(flowType); var registered = new VariableDefinition(task);
        registration.Body.Variables.Add(flow); registration.Body.Variables.Add(registered);
        il = registration.Body.GetILProcessor(); var suppress = il.Create(OpCodes.Call, suppressFlow);
        il.Emit(OpCodes.Call, flowSuppressed); il.Emit(OpCodes.Brfalse, suppress);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Call, register); il.Emit(OpCodes.Ret);
        il.Append(suppress); il.Emit(OpCodes.Stloc, flow);
        var registerStart = il.Create(OpCodes.Ldarg_0); var restoreFlow = il.Create(OpCodes.Ldloca, flow); var registerDone = il.Create(OpCodes.Ldloc, registered);
        il.Append(registerStart); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Call, register); il.Emit(OpCodes.Stloc, registered); il.Emit(OpCodes.Leave, registerDone);
        il.Append(restoreFlow); il.Emit(OpCodes.Call, undoFlow); il.Emit(OpCodes.Endfinally); il.Append(registerDone); il.Emit(OpCodes.Ret);
        registration.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = registerStart, TryEnd = restoreFlow, HandlerStart = restoreFlow, HandlerEnd = registerDone,
        });

        var saved = new VariableDefinition(state); callback.Body.Variables.Add(saved);
        il = callback.Body.GetILProcessor(); var valid = il.Create(OpCodes.Ldloc, saved); var callbackDone = il.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Castclass, state); il.Emit(OpCodes.Stloc, saved);
        il.Emit(OpCodes.Ldloc, saved); il.Emit(OpCodes.Ldfld, stateTask); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Call, referenceEquals); il.Emit(OpCodes.Brtrue, valid);
        il.Emit(OpCodes.Ldstr, "activation-timer-driver-task-identity"); il.Emit(OpCodes.Newobj, invalid); il.Emit(OpCodes.Throw);
        il.Append(valid); il.Emit(OpCodes.Ldfld, stateEpoch); il.Emit(OpCodes.Ldsfld, epoch); il.Emit(OpCodes.Bne_Un, callbackDone);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Callvirt, cancelled); il.Emit(OpCodes.Brtrue, callbackDone);
        var success = il.Create(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Callvirt, succeeded); il.Emit(OpCodes.Brtrue, success);
        il.Emit(OpCodes.Ldstr, "activation-timer-driver-completion"); il.Emit(OpCodes.Newobj, invalid); il.Emit(OpCodes.Throw);
        il.Append(success); il.Emit(OpCodes.Call, handler); il.Append(callbackDone);

        il = rearm.Body.GetILProcessor(); var rearmDone = il.Create(OpCodes.Ret);
        il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Ldsfld, epoch); il.Emit(OpCodes.Bne_Un, rearmDone);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Call, set); il.Append(rearmDone);

        // Preserve the complete original handler, including its FailFast catch.
        var handlerEpoch = new VariableDefinition(module.TypeSystem.Int64); handler.Body.Variables.Add(handlerEpoch); handler.Body.InitLocals = true;
        il = handler.Body.GetILProcessor(); var first = handler.Body.Instructions[0];
        il.InsertBefore(first, il.Create(OpCodes.Ldsfld, epoch)); il.InsertBefore(first, il.Create(OpCodes.Stloc, handlerEpoch));
        var oldRearm = handler.Body.Instructions.Single(instruction => instruction.Operand is MethodReference reference && reference.FullName == set.FullName);
        il.InsertBefore(oldRearm, il.Create(OpCodes.Ldloc, handlerEpoch)); oldRearm.Operand = rearm; handler.Body.MaxStackSize = Math.Max(handler.Body.MaxStackSize, 3);

        // Only the original TimerQueue producer receives this token/continuation.
        set.Body = new MethodBody(set) { InitLocals = true, MaxStackSize = 8 };
        var driver = new VariableDefinition(task); set.Body.Variables.Add(driver); il = set.Body.GetILProcessor(); var setDone = il.Create(OpCodes.Ret);
        il.Emit(OpCodes.Call, active); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Beq, setDone);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldc_I8, long.MaxValue); il.Emit(OpCodes.Beq, setDone);
        il.Emit(OpCodes.Ldsfld, shortest); il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ble, setDone);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Stsfld, shortest);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Sub); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Call, maximum); il.Emit(OpCodes.Conv_U8);
        il.Emit(OpCodes.Ldc_I4, 1000); il.Emit(OpCodes.Conv_U8); il.Emit(OpCodes.Mul); il.Emit(OpCodes.Ldc_I4, 1000); il.Emit(OpCodes.Conv_U8); il.Emit(OpCodes.Mul);
        il.Emit(OpCodes.Call, subscribe); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Call, token); il.Emit(OpCodes.Call, registration); il.Emit(OpCodes.Stloc, driver);
        il.Emit(OpCodes.Ldloc, driver); il.Emit(OpCodes.Ldnull); il.Emit(OpCodes.Ldftn, callback); il.Emit(OpCodes.Newobj, actionConstructor);
        il.Emit(OpCodes.Ldloc, driver); il.Emit(OpCodes.Ldsfld, epoch); il.Emit(OpCodes.Newobj, stateConstructor); il.Emit(OpCodes.Call, defaultScheduler);
        il.Emit(OpCodes.Callvirt, continueWith); il.Emit(OpCodes.Pop); il.Append(setDone);

        var originalSource = new VariableDefinition(ctsType); var queues = new VariableDefinition(instances.ReturnType); var index = new VariableDefinition(module.TypeSystem.Int32);
        retire.Body.Variables.Add(originalSource); retire.Body.Variables.Add(queues); retire.Body.Variables.Add(index);
        il = retire.Body.GetILProcessor(); var retireDone = il.Create(OpCodes.Ret); var epochAvailable = il.Create(OpCodes.Ldsfld, source);
        il.Emit(OpCodes.Call, active); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Bne_Un, retireDone);
        il.Emit(OpCodes.Ldsfld, source); il.Emit(OpCodes.Brfalse, retireDone);
        il.Emit(OpCodes.Ldsfld, epoch); il.Emit(OpCodes.Ldc_I8, long.MaxValue); il.Emit(OpCodes.Bne_Un, epochAvailable);
        il.Emit(OpCodes.Ldstr, "activation-timer-driver-epoch-limit"); il.Emit(OpCodes.Newobj, invalid); il.Emit(OpCodes.Throw);
        il.Append(epochAvailable); il.Emit(OpCodes.Stloc, originalSource); il.Emit(OpCodes.Ldnull); il.Emit(OpCodes.Stsfld, source);
        il.Emit(OpCodes.Ldsfld, epoch); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Conv_I8); il.Emit(OpCodes.Add); il.Emit(OpCodes.Stsfld, epoch);
        il.Emit(OpCodes.Ldc_I8, long.MaxValue); il.Emit(OpCodes.Stsfld, shortest);
        il.Emit(OpCodes.Call, instances); il.Emit(OpCodes.Stloc, queues); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Stloc, index);
        var loopTest = il.Create(OpCodes.Ldloc, index); var loopBody = il.Create(OpCodes.Ldloc, queues); il.Emit(OpCodes.Br, loopTest); il.Append(loopBody);
        foreach (var field in new[] { armed, inList, due })
        {
            if (field != armed) il.Emit(OpCodes.Ldloc, queues);
            il.Emit(OpCodes.Ldloc, index); il.Emit(OpCodes.Ldelem_Ref);
            if (field == due) il.Emit(OpCodes.Ldc_I8, long.MaxValue); else il.Emit(OpCodes.Ldc_I4_0);
            il.Emit(OpCodes.Stfld, field);
        }
        il.Emit(OpCodes.Ldloc, index); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Add); il.Emit(OpCodes.Stloc, index);
        il.Append(loopTest); il.Emit(OpCodes.Ldloc, queues); il.Emit(OpCodes.Ldlen); il.Emit(OpCodes.Conv_I4); il.Emit(OpCodes.Blt, loopBody);
        var absentList = il.Create(OpCodes.Pop); var afterList = il.Create(OpCodes.Nop);
        il.Emit(OpCodes.Ldsfld, scheduled); il.Emit(OpCodes.Dup); il.Emit(OpCodes.Brfalse, absentList); il.Emit(OpCodes.Callvirt, clear); il.Emit(OpCodes.Br, afterList);
        il.Append(absentList); il.Append(afterList);
        // Reset state before cancellation: captured ExecutionContext may reenter.
        // Never touch s_scheduledTimersToFire or the original ThreadPool queue.
        var cancelStart = il.Create(OpCodes.Ldloc, originalSource); var cleanup = il.Create(OpCodes.Ldloc, originalSource);
        il.Append(cancelStart); il.Emit(OpCodes.Callvirt, cancel); il.Emit(OpCodes.Leave, retireDone);
        il.Append(cleanup); il.Emit(OpCodes.Callvirt, dispose); il.Emit(OpCodes.Endfinally); il.Append(retireDone);
        retire.Body.ExceptionHandlers.Add(new ExceptionHandler(ExceptionHandlerType.Finally) {
            TryStart = cancelStart, TryEnd = cleanup, HandlerStart = cleanup, HandlerEnd = retireDone,
        });
        // Changing the existing ret target also covers original early branches.
        var returnInstruction = delete.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Ret);
        returnInstruction.OpCode = OpCodes.Call; returnInstruction.Operand = retire;
        delete.Body.GetILProcessor().InsertAfter(returnInstruction, Instruction.Create(OpCodes.Ret));
        return new[] { set, handler, delete };
    }
}

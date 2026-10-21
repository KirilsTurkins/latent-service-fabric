using Mono.Cecil;
using Mono.Cecil.Cil;

// These methods live on ExecutionContext itself, where its original private
// immutable map is accessible. They never run an extra context transition.
internal static class ManagedWorkContext
{
    private static void Need(bool value)
    {
        if (!value) throw new InvalidDataException("managed-work-context-preimage");
    }

    internal static MethodDefinition[] Install(ModuleDefinition module,
        IReadOnlyDictionary<string, MethodDefinition> registry)
    {
        var context = module.GetTypes().Single(type => type.FullName == "System.Threading.ExecutionContext");
        var local = module.GetTypes().Single(type => type.FullName == "System.Threading.IAsyncLocal");
        var map = module.GetTypes().Single(type => type.FullName == "System.Threading.IAsyncLocalValueMap");
        var maps = module.GetTypes().Single(type => type.FullName == "System.Threading.AsyncLocalValueMap");
        var values = context.Fields.Single(field => field.Name == "m_localValues");
        var notifications = context.Fields.Single(field => field.Name == "m_localChangeNotifications");
        var suppressed = context.Fields.Single(field => field.Name == "m_isFlowSuppressed");
        var fallback = context.Fields.Single(field => field.Name == "Default");
        var create = context.Methods.Single(method => method.IsConstructor && method.Parameters.Count == 3);
        var get = map.Methods.Single(method => method.Name == "TryGetValue");
        var set = map.Methods.Single(method => method.Name == "Set");
        var empty = maps.Methods.Single(method => method.Name == "get_Empty");
        Need(values.IsPrivate && values.IsInitOnly && values.FieldType.FullName == map.FullName
            && notifications.IsPrivate && notifications.IsInitOnly
            && notifications.FieldType.FullName == local.FullName + "[]"
            && suppressed.IsPrivate && suppressed.IsInitOnly
            && fallback.IsStatic && fallback.IsInitOnly
            && create.IsPrivate && create.Parameters[0].ParameterType.FullName == map.FullName
            && create.Parameters[1].ParameterType.FullName == local.FullName + "[]"
            && create.Parameters[2].ParameterType.MetadataType == MetadataType.Boolean
            && get.Parameters.Count == 2 && get.ReturnType.MetadataType == MetadataType.Boolean
            && set.Parameters.Count == 3 && set.ReturnType.FullName == map.FullName
            && empty.IsStatic && empty.ReturnType.FullName == map.FullName
            && !context.Methods.Any(method => method.Name.StartsWith("LsfManagedWork", StringComparison.Ordinal)));

        var read = new MethodDefinition("LsfManagedWorkRead", MethodAttributes.Assembly |
            MethodAttributes.Static | MethodAttributes.HideBySig, module.TypeSystem.Object);
        read.Parameters.Add(new ParameterDefinition(context));
        read.Parameters.Add(new ParameterDefinition(local));
        read.Body.InitLocals = true;
        read.Body.MaxStackSize = 3;
        var result = new VariableDefinition(module.TypeSystem.Object);
        read.Body.Variables.Add(result);
        var il = read.Body.GetILProcessor();
        var none = il.Create(OpCodes.Ldnull);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Brfalse, none);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldfld, values); il.Emit(OpCodes.Brfalse, none);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldfld, values);
        il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldloca, result);
        il.Emit(OpCodes.Callvirt, get); il.Emit(OpCodes.Pop); il.Emit(OpCodes.Ldloc, result); il.Emit(OpCodes.Ret);
        il.Append(none); il.Emit(OpCodes.Ret);
        context.Methods.Add(read);

        var write = new MethodDefinition("LsfManagedWorkWrite", MethodAttributes.Assembly |
            MethodAttributes.Static | MethodAttributes.HideBySig, context);
        write.Parameters.Add(new ParameterDefinition(context));
        write.Parameters.Add(new ParameterDefinition(local));
        write.Parameters.Add(new ParameterDefinition(module.TypeSystem.Object));
        write.Body.InitLocals = true;
        write.Body.MaxStackSize = 4;
        var selected = new VariableDefinition(context);
        var selectedMap = new VariableDefinition(map);
        var old = new VariableDefinition(new ArrayType(local));
        var copied = new VariableDefinition(new ArrayType(local));
        var length = new VariableDefinition(module.TypeSystem.Int32);
        var index = new VariableDefinition(module.TypeSystem.Int32);
        foreach (var variable in new[] { selected, selectedMap, old, copied, length, index }) write.Body.Variables.Add(variable);
        il = write.Body.GetILProcessor();
        var haveContext = il.Create(OpCodes.Stloc, selected);
        var haveMap = il.Create(OpCodes.Ldarg_1);
        var noArray = il.Create(OpCodes.Ldc_I4_0);
        var haveLength = il.Create(OpCodes.Stloc, length);
        var check = il.Create(OpCodes.Ldloc, index);
        var allocate = il.Create(OpCodes.Ldloc, length);
        var copyCheck = il.Create(OpCodes.Ldloc, index);
        var append = il.Create(OpCodes.Ldloc, copied);
        var construct = il.Create(OpCodes.Ldloc, selectedMap);
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Dup); il.Emit(OpCodes.Brtrue, haveContext);
        il.Emit(OpCodes.Pop); il.Emit(OpCodes.Ldsfld, fallback); il.Append(haveContext);
        il.Emit(OpCodes.Ldloc, selected); il.Emit(OpCodes.Ldfld, values); il.Emit(OpCodes.Dup);
        il.Emit(OpCodes.Brtrue, haveMap); il.Emit(OpCodes.Pop); il.Emit(OpCodes.Call, empty);
        il.Append(haveMap); il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Ldc_I4_0);
        il.Emit(OpCodes.Callvirt, set); il.Emit(OpCodes.Stloc, selectedMap);
        il.Emit(OpCodes.Ldloc, selected); il.Emit(OpCodes.Ldfld, notifications); il.Emit(OpCodes.Stloc, old);
        il.Emit(OpCodes.Ldloc, old); il.Emit(OpCodes.Brfalse, noArray);
        il.Emit(OpCodes.Ldloc, old); il.Emit(OpCodes.Ldlen); il.Emit(OpCodes.Conv_I4); il.Emit(OpCodes.Br, haveLength);
        il.Append(noArray); il.Append(haveLength); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Stloc, index);
        il.Emit(OpCodes.Br, check);
        var search = il.Create(OpCodes.Ldloc, old);
        il.Append(search); il.Emit(OpCodes.Ldloc, index); il.Emit(OpCodes.Ldelem_Ref); il.Emit(OpCodes.Ldarg_1);
        var next = il.Create(OpCodes.Ldloc, index);
        il.Emit(OpCodes.Bne_Un, next); il.Emit(OpCodes.Ldloc, old); il.Emit(OpCodes.Stloc, copied); il.Emit(OpCodes.Br, construct);
        il.Append(next); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Add); il.Emit(OpCodes.Stloc, index);
        il.Append(check); il.Emit(OpCodes.Ldloc, length); il.Emit(OpCodes.Blt, search);
        il.Append(allocate); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Add_Ovf); il.Emit(OpCodes.Newarr, local);
        il.Emit(OpCodes.Stloc, copied); il.Emit(OpCodes.Ldc_I4_0); il.Emit(OpCodes.Stloc, index); il.Emit(OpCodes.Br, copyCheck);
        var copy = il.Create(OpCodes.Ldloc, copied);
        il.Append(copy); il.Emit(OpCodes.Ldloc, index); il.Emit(OpCodes.Ldloc, old); il.Emit(OpCodes.Ldloc, index);
        il.Emit(OpCodes.Ldelem_Ref); il.Emit(OpCodes.Stelem_Ref);
        il.Emit(OpCodes.Ldloc, index); il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Add); il.Emit(OpCodes.Stloc, index);
        il.Append(copyCheck); il.Emit(OpCodes.Ldloc, length); il.Emit(OpCodes.Blt, copy);
        il.Append(append); il.Emit(OpCodes.Ldloc, length); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Stelem_Ref);
        il.Append(construct); il.Emit(OpCodes.Ldloc, copied); il.Emit(OpCodes.Ldloc, selected);
        il.Emit(OpCodes.Ldfld, suppressed); il.Emit(OpCodes.Newobj, create); il.Emit(OpCodes.Ret);
        context.Methods.Add(write);

        var registryType = module.GetTypes().Single(type => type.FullName == "Lsf.CompilerOwned.ManagedWorkRuntime");
        var key = registryType.Fields.Single(field => field.Name == "current");
        var readStub = registry.Values.Single(method => method.Name == "ContextValue");
        var writeStub = registry.Values.Single(method => method.Name == "ContextWithOwner");
        readStub.Body = new MethodBody(readStub);
        il = readStub.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldsfld, key); il.Emit(OpCodes.Call, read); il.Emit(OpCodes.Ret);
        writeStub.Body = new MethodBody(writeStub);
        il = writeStub.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldsfld, key); il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Call, write); il.Emit(OpCodes.Ret);
        return new[] { read, write };
    }
}

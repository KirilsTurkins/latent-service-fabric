using Mono.Cecil;
using Mono.Cecil.Cil;

// Closed copier for this tool's own compiled registry. Every external type must
// already belong to the authenticated original CoreLib. No helper assembly,
// host-CLR facade, reflection lookup or new deployed dependency is introduced.
internal sealed class ManagedWorkCopy
{
    private const string Registry = "Lsf.CompilerOwned.ManagedWorkRuntime";
    private readonly ModuleDefinition target;
    private readonly Dictionary<string, TypeDefinition> core;
    private readonly Dictionary<TypeDefinition, TypeDefinition> types = new();
    private readonly Dictionary<MethodDefinition, MethodDefinition> methods = new();
    private readonly Dictionary<FieldDefinition, FieldDefinition> fields = new();
    private readonly Dictionary<string, MethodDefinition> methodNames = new();
    private readonly Dictionary<string, FieldDefinition> fieldNames = new();

    internal ManagedWorkCopy(ModuleDefinition target)
    {
        this.target = target;
        core = target.GetTypes().ToDictionary(type => type.FullName);
    }

    private static void Need(bool value)
    {
        if (!value) throw new InvalidDataException("managed-work-closed-copy");
    }

    private static bool CompilerAnnotation(CustomAttribute value) => value.AttributeType.FullName is
        "System.Runtime.CompilerServices.NullableAttribute" or
        "System.Runtime.CompilerServices.NullableContextAttribute" or
        "System.Runtime.CompilerServices.CompilerGeneratedAttribute" or
        "System.Runtime.CompilerServices.TupleElementNamesAttribute";

    private static string Shape(TypeReference value) => value switch
    {
        GenericParameter parameter => (parameter.Type == GenericParameterType.Type ? "!" : "!!") + parameter.Position,
        GenericInstanceType generic => Shape(generic.ElementType) + "<" + string.Join(",", generic.GenericArguments.Select(Shape)) + ">",
        ArrayType array => Shape(array.ElementType) + "[]",
        ByReferenceType reference => Shape(reference.ElementType) + "&",
        _ => value.FullName,
    };

    private TypeReference Rebind(TypeReference value)
    {
        if (value is GenericParameter) return value;
        if (value is GenericInstanceType generic)
        {
            var result = new GenericInstanceType(Rebind(generic.ElementType));
            foreach (var argument in generic.GenericArguments) result.GenericArguments.Add(Rebind(argument));
            return result;
        }
        if (value is ArrayType array)
        {
            Need(array.IsVector);
            return new ArrayType(Rebind(array.ElementType));
        }
        if (value is ByReferenceType reference) return new ByReferenceType(Rebind(reference.ElementType));
        if (value is PointerType pointer) return new PointerType(Rebind(pointer.ElementType));
        Need(value is not TypeSpecification);
        var copied = types.Values.SingleOrDefault(type => type.FullName == value.FullName);
        if (copied is not null) return copied;
        Need(core.ContainsKey(value.FullName));
        value.Scope = target;
        if (value.DeclaringType is not null) value.DeclaringType = Rebind(value.DeclaringType);
        return value;
    }

    private TypeReference Type(TypeReference source)
    {
        if (source is GenericInstanceType generic)
        {
            var result = new GenericInstanceType(Type(generic.ElementType));
            foreach (var argument in generic.GenericArguments) result.GenericArguments.Add(Type(argument));
            return result;
        }
        if (source is ArrayType array)
        {
            Need(array.IsVector);
            return new ArrayType(Type(array.ElementType));
        }
        if (source is ByReferenceType reference) return new ByReferenceType(Type(reference.ElementType));
        if (source is PointerType pointer) return new PointerType(Type(pointer.ElementType));
        if (source is RequiredModifierType required)
            return new RequiredModifierType(Type(required.ModifierType), Type(required.ElementType));
        if (source is OptionalModifierType optional)
            return new OptionalModifierType(Type(optional.ModifierType), Type(optional.ElementType));
        if (source is GenericParameter parameter)
        {
            Need(parameter.Owner is TypeReference);
            var owner = Type((TypeReference)parameter.Owner).GetElementType();
            Need(parameter.Position >= 0 && parameter.Position < owner.GenericParameters.Count);
            return owner.GenericParameters[parameter.Position];
        }
        if (source is TypeDefinition definition && types.TryGetValue(definition, out var copied)) return copied;
        var local = types.Values.SingleOrDefault(type => type.FullName == source.FullName);
        if (local is not null) return local;
        Need(core.TryGetValue(source.FullName, out var original));
        return original!;
    }

    private MethodReference Method(MethodReference source)
    {
        Need(source is not GenericInstanceMethod && !source.HasGenericParameters);
        if (methodNames.TryGetValue(source.FullName, out var copied)) return copied;
        var declaring = Type(source.DeclaringType);
        var original = declaring.GetElementType().Resolve();
        Need(original.Module == target && original.Methods.Any(method => method.Name == source.Name
            && method.HasThis == source.HasThis && method.Parameters.Count == source.Parameters.Count
            && method.GenericParameters.Count == source.GenericParameters.Count
            && Shape(method.ReturnType) == Shape(source.ReturnType)
            && method.Parameters.Select(p => Shape(p.ParameterType))
                .SequenceEqual(source.Parameters.Select(p => Shape(p.ParameterType)))));
        // MemberRef signatures retain !0/!1 rather than a TypeDef's cosmetic
        // generic parameter names. Preserve those exact serialized signatures.
        var result = target.ImportReference(source);
        result.DeclaringType = Rebind(result.DeclaringType);
        result.ReturnType = Rebind(result.ReturnType);
        foreach (var parameter in result.Parameters) parameter.ParameterType = Rebind(parameter.ParameterType);
        return result;
    }

    private FieldReference Field(FieldReference source)
    {
        if (fieldNames.TryGetValue(source.FullName, out var copied)) return copied;
        var declaring = Type(source.DeclaringType);
        var original = declaring.GetElementType().Resolve();
        Need(original.Module == target && original.Fields.Any(field => field.Name == source.Name
            && Shape(field.FieldType) == Shape(source.FieldType)));
        var result = target.ImportReference(source);
        result.DeclaringType = Rebind(result.DeclaringType);
        result.FieldType = Rebind(result.FieldType);
        return result;
    }

    private void Declare(TypeDefinition source, TypeDefinition? parent)
    {
        Need(!source.HasGenericParameters && source.Interfaces.Count == 0 && source.Properties.Count == 0
            && source.Events.Count == 0
            && (source.BaseType is not null || (source.IsInterface && source.FullName == Registry + "/ContextSource"))
            && source.CustomAttributes.All(CompilerAnnotation));
        var result = new TypeDefinition(source.Namespace, source.Name, source.Attributes);
        if (parent is null) target.Types.Add(result); else parent.NestedTypes.Add(result);
        types.Add(source, result);
        foreach (var nested in source.NestedTypes) Declare(nested, result);
    }

    internal IReadOnlyDictionary<string, MethodDefinition> Copy(ModuleDefinition source)
    {
        Need(!core.ContainsKey(Registry));
        var originalReferences = target.AssemblyReferences.ToArray();
        var registry = source.GetTypes().Single(type => type.FullName == Registry);
        Declare(registry, null);
        Need(types.Count is >= 4 and <= 8);
        foreach (var (original, copied) in types)
        {
            copied.BaseType = original.BaseType is null ? null : Type(original.BaseType);
            copied.ClassSize = original.ClassSize;
            copied.PackingSize = original.PackingSize;
            foreach (var field in original.Fields)
            {
                Need(!field.HasMarshalInfo && field.InitialValue.Length == 0 && field.CustomAttributes.All(CompilerAnnotation));
                var result = new FieldDefinition(field.Name, field.Attributes, Type(field.FieldType));
                if (field.HasConstant) result.Constant = field.Constant;
                copied.Fields.Add(result);
                fields.Add(field, result);
                fieldNames.Add(field.FullName, result);
            }
            foreach (var method in original.Methods)
            {
                Need(!method.HasGenericParameters && !method.IsPInvokeImpl
                    && (method.HasBody || (original.IsInterface && method.IsAbstract))
                    && method.Overrides.Count == 0 && method.CustomAttributes.All(CompilerAnnotation)
                    && method.MethodReturnType.CustomAttributes.All(CompilerAnnotation)
                    && method.Parameters.All(parameter => !parameter.HasMarshalInfo && parameter.CustomAttributes.All(CompilerAnnotation)));
                var result = new MethodDefinition(method.Name, method.Attributes, Type(method.ReturnType))
                {
                    ImplAttributes = method.ImplAttributes,
                    CallingConvention = method.CallingConvention,
                };
                foreach (var parameter in method.Parameters)
                    result.Parameters.Add(new ParameterDefinition(parameter.Name, parameter.Attributes, Type(parameter.ParameterType)));
                copied.Methods.Add(result);
                methods.Add(method, result);
                methodNames.Add(method.FullName, result);
            }
        }
        Need(methods.Count is >= 24 and <= 64 && fields.Count is >= 24 and <= 64);
        foreach (var (original, copied) in methods)
        {
            if (!original.HasBody)
            {
                Need(copied.IsAbstract && copied.DeclaringType.IsInterface);
                continue;
            }
            copied.Body = new MethodBody(copied) { InitLocals = original.Body.InitLocals, MaxStackSize = original.Body.MaxStackSize };
            var variables = new Dictionary<VariableDefinition, VariableDefinition>();
            foreach (var variable in original.Body.Variables)
            {
                var result = new VariableDefinition(Type(variable.VariableType));
                variables.Add(variable, result);
                copied.Body.Variables.Add(result);
            }
            var instructions = original.Body.Instructions.ToDictionary(instruction => instruction,
                instruction => Instruction.Create(OpCodes.Nop));
            foreach (var instruction in original.Body.Instructions)
            {
                var result = instructions[instruction];
                result.OpCode = instruction.OpCode;
                result.Operand = instruction.Operand switch
                {
                    null => null,
                    Instruction branch => instructions[branch],
                    Instruction[] branches => branches.Select(branch => instructions[branch]).ToArray(),
                    MethodReference method => Method(method),
                    FieldReference field => Field(field),
                    TypeReference type => Type(type),
                    VariableDefinition variable => variables[variable],
                    ParameterDefinition parameter => copied.Parameters[parameter.Index],
                    string or sbyte or byte or int or long or float or double => instruction.Operand,
                    _ => throw new InvalidDataException("managed-work-copy-unknown-operand"),
                };
                copied.Body.Instructions.Add(result);
            }
            Instruction? At(Instruction? instruction) => instruction is null ? null : instructions[instruction];
            foreach (var handler in original.Body.ExceptionHandlers)
                copied.Body.ExceptionHandlers.Add(new ExceptionHandler(handler.HandlerType)
                {
                    TryStart = At(handler.TryStart), TryEnd = At(handler.TryEnd),
                    HandlerStart = At(handler.HandlerStart), HandlerEnd = At(handler.HandlerEnd),
                    FilterStart = At(handler.FilterStart), CatchType = handler.CatchType is null ? null : Type(handler.CatchType),
                });
            Need(TaskWait.BodyIdentity(original) == TaskWait.BodyIdentity(copied));
        }
        // ImportReference may transiently register the tool's reference facade;
        // every copied signature above was rebound and validated in CoreLib.
        foreach (var reference in target.AssemblyReferences.Except(originalReferences).ToArray())
            target.AssemblyReferences.Remove(reference);
        return methodNames;
    }
}

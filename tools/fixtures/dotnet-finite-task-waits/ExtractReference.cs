using System.Security.Cryptography;
using System.Text.Json;
using Mono.Cecil;
using Mono.Cecil.Cil;
if (args.Length != 4) throw new ArgumentException("Expected derived CoreLib, original probe, output probe, proof");
string Hash(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));
if (Hash(args[0]) != "a4319cf5f26e186ffedefa623e81f0636cd2f6131ec980e3e723768277405872" ||
    Hash(typeof(ModuleDefinition).Assembly.Location) != "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7") throw new Exception("unpinned-IL-control");
using var source = ModuleDefinition.ReadModule(args[0]);
using var target = ModuleDefinition.ReadModule(args[1]);
var method = source.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop").Methods.Single(method => method.Name == "LsfWaitForActualTaskOrTimeout");
var type = target.Types.Single(type => type.FullName == "WaitCandidate");
var replacement = type.Methods.Single(candidate => candidate.Name == "Wait");
var pump = type.Methods.Single(candidate => candidate.Name == "Pump");
if (method.Parameters.Count != 3 || method.Body.Instructions.Count > 128 || method.Body.ExceptionHandlers.Count != 2 || method.Body.Variables.Count != 2 || File.Exists(args[2]) || File.Exists(args[3])) throw new Exception("unknown-control-shape");
replacement.Body = new MethodBody(replacement) { InitLocals = method.Body.InitLocals, MaxStackSize = method.Body.MaxStackSize };
var locals = method.Body.Variables.ToDictionary(variable => variable, variable => new VariableDefinition(target.ImportReference(variable.VariableType)));
foreach (var variable in method.Body.Variables) replacement.Body.Variables.Add(locals[variable]);
var instructions = method.Body.Instructions.ToDictionary(instruction => instruction, instruction => Instruction.Create(OpCodes.Nop));
int mappedPump = 0;
object? Import(object? operand) {
    switch (operand) {
        case null: return null;
        case Instruction branch: return instructions[branch];
        case Instruction[] branches: return branches.Select(branch => instructions[branch]).ToArray();
        case VariableDefinition variable: return locals[variable];
        case ParameterDefinition parameter: return replacement.Parameters[parameter.Index];
        case MethodReference reference:
            if (reference.FullName == "System.Boolean System.Threading.WasiEventLoop::LsfWaitForActualTaskCompletion(System.Threading.Tasks.Task)") { mappedPump++; return pump; }
            if (reference.DeclaringType.FullName.StartsWith("System.Threading.WasiEventLoop", StringComparison.Ordinal)) throw new Exception("unexpected-private-IL-control");
            return target.ImportReference(reference);
        case TypeReference reference: return target.ImportReference(reference);
        case string or int or long or float or double or byte or sbyte: return operand;
        default: throw new Exception("unknown-IL-control-operand");
    }
}
foreach (var original in method.Body.Instructions) {
    var instruction = instructions[original]; instruction.OpCode = original.OpCode; instruction.Operand = Import(original.Operand);
    replacement.Body.Instructions.Add(instruction);
}
Instruction? End(Instruction? instruction) => instruction is null ? null : instructions[instruction];
foreach (var handler in method.Body.ExceptionHandlers) replacement.Body.ExceptionHandlers.Add(new ExceptionHandler(handler.HandlerType) {
    TryStart = End(handler.TryStart), TryEnd = End(handler.TryEnd), HandlerStart = End(handler.HandlerStart), HandlerEnd = End(handler.HandlerEnd),
    FilterStart = End(handler.FilterStart), CatchType = handler.CatchType is null ? null : target.ImportReference(handler.CatchType)
});
if (mappedPump != 1 || !replacement.Body.Instructions.Select(instruction => instruction.OpCode.Code).SequenceEqual(method.Body.Instructions.Select(instruction => instruction.OpCode.Code))) throw new Exception("IL-control-copy-changed");
target.Write(args[2]);
File.WriteAllText(args[3], JsonSerializer.Serialize(new {
    derivedCorelib = Hash(args[0]), originalProbe = Hash(args[1]), controlledProbe = Hash(args[2]),
    method = method.FullName, instructions = method.Body.Instructions.Count, finallyHandlers = method.Body.ExceptionHandlers.Count,
    sourceOpcodesPreserved = true, sourceBranchesAndLocalsAndHandlersPreserved = true,
    exactlyOnePrivatePumpCallMappedToHostAwaiter = mappedPump, wasmRuntimeQualified = false
}, new JsonSerializerOptions { WriteIndented = true }));

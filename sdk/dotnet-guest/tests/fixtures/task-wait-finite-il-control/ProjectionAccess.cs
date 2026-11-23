// Host-only control: execute the copied pinned helper's private CoreLib field
// reads and constructor, rather than replacing the context factory with a model.
// This attribute is not copied into the guest or its compiler-owned helpers.
[assembly: System.Runtime.CompilerServices.IgnoresAccessChecksTo("System.Private.CoreLib")]

namespace System.Runtime.CompilerServices
{
    [AttributeUsage(AttributeTargets.Assembly, AllowMultiple = true)]
    internal sealed class IgnoresAccessChecksToAttribute(string assemblyName) : Attribute
    {
        public string AssemblyName { get; } = assemblyName;
    }
}

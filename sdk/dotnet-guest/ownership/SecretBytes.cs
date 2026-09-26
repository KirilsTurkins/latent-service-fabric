using System;
using System.Runtime.CompilerServices;
using System.Threading;

namespace Lsf.Guest;

internal static class SecretBytes
{
    // CryptographicOperations.ZeroMemory is unsupported by this pinned WASI
    // library profile. Volatile stores must remain observable even when the
    // owner has no further reads; do not substitute an ordinary dead store.
    [MethodImpl(MethodImplOptions.NoInlining | MethodImplOptions.NoOptimization)]
    internal static void Zero(byte[] value)
    {
        for (int index = 0; index < value.Length; index++)
            Volatile.Write(ref value[index], (byte)0);
        GC.KeepAlive(value);
    }
}

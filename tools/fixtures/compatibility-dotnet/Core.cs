using System;
using System.IO;
using System.Runtime.CompilerServices;

namespace OutsideDiagnosticsData;

// Ordinary captured dependency; metadata observation never loads this assembly.
public sealed class Core
{
    private static int initializations, constructors, denials;
    static Core() { initializations++; Require(Fallback() == 42); }
    public Core() { constructors++; Require(Fallback() == 42); }
    private static void Require(bool value)
    {
        if (!value) throw new InvalidOperationException("diagnostics-original-library-state");
    }
    public static int Fallback()
    {
        try
        {
            using var ignored = File.OpenRead("diagnostics-never-contact");
            throw new InvalidOperationException("diagnostics-unexpected-filesystem-success");
        }
        catch (PlatformNotSupportedException) { denials++; return 6 * 7; }
    }
    public static void Uncaught()
    {
        using var ignored = File.OpenRead("diagnostics-never-contact");
        throw new InvalidOperationException("diagnostics-unexpected-filesystem-success");
    }
    // Compiler absence of this exact wrapper remains an unknown API result.
    // No inlining permits the selected graph to query its own method identity.
    [MethodImpl(MethodImplOptions.NoInlining)]
    public static int DeadUnsupported()
    {
        using var ignored = File.OpenRead("diagnostics-never-contact");
        return 1;
    }
    private static class BadInitialization
    {
        static BadInitialization() { Uncaught(); }
        public static int Value() => 0;
    }
    public static void InitializationFailure() { _ = BadInitialization.Value(); }
    public static string State(int expectedDenials)
    {
        Require(initializations == 1 && constructors == 1 && denials == expectedDenials);
        return "init=1|ctor=1|denied=" + denials;
    }
}

namespace CapsuleWorld.wit.Exports.latent.greeting.v1_0_0;

/// <summary>Typed component export; no RPC client or application process.</summary>
public class GreetingExportsImpl : IGreetingExports
{
    public static string Greet(string name)
    {
        ArgumentNullException.ThrowIfNull(name);
        return $"Hello, {name}!";
    }
}

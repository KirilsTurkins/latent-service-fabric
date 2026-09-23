namespace CapsuleWorld.wit.exports.latent.greeting;

/// <summary>Typed component export; no RPC client or application process.</summary>
public class GreetingImpl : IGreeting
{
    public static string Greet(string name)
    {
        ArgumentNullException.ThrowIfNull(name);
        return $"Hello, {name}!";
    }
}

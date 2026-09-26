namespace Latent.Sdk.SemanticTests;

internal static class Program
{
    public static async Task Main()
    {
        ProfileVectors.Run();
        await ProfileLifetime.Run();
        Console.WriteLine(".NET client profile semantic fixtures passed");
    }
}

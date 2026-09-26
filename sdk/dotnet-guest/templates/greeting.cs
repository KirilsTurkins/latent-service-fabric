using ServiceWorld;
using Lsf.Guest;
namespace ServiceWorld.wit.Exports.examples.greeting;

// lsf-example-begin: capsule
public class ApiExportsImpl : IApiExports
{
    public static Result<string, string> Greet(string name)
    {
        string clean = Text.Trim(name);
        if (clean.Length == 0) return Result<string, string>.Err("Please enter a name.");
        if (Text.Utf8Length(clean) > 100) return Result<string, string>.Err("Use a name of at most 100 bytes.");
        return Result<string, string>.Ok($"Hello, {clean}!");
    }
}
// lsf-example-end: capsule

using Lsf.Guest;
using OutsideDiagnostics;
using ServiceWorld;

namespace ServiceWorld.wit.Exports.examples.greeting;

public class ApiExportsImpl : IApiExports
{
    public static Result<string, string> Greet(string name)
        => Result<string, string>.Ok(new Library().Run(name));
}

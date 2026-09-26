namespace ServiceWorld.wit.Exports.tests.local;
public class ApiExportsImpl : IApiExports
{
    public static uint Answer() => 42;
    public static Result<uint, string> Fail() => Result<uint, string>.Err("declared application failure");
    public static uint Spin() { while (true) {} }
}

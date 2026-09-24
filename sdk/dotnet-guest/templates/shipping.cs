using ServiceWorld;
namespace ServiceWorld.wit.Exports.examples.shipping;

// lsf-example-begin: capsule
public class ApiExportsImpl : IApiExports
{
    public static Result<uint, string> Quote(uint items, bool express)
    {
        if (items < 1 || items > 100) return Result<uint, string>.Err("Choose between 1 and 100 items.");
        return Result<uint, string>.Ok((express ? 1200U : 500U) + items * 75U);
    }
}
// lsf-example-end: capsule

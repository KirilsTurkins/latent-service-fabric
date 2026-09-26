using ServiceWorld;
using Lsf.Guest;
namespace ServiceWorld.wit.Exports.examples.wordCount;

// lsf-example-begin: capsule
public class ApiExportsImpl : IApiExports
{
    public static Result<uint, string> Count(string text)
    {
        if (Text.Utf8Length(text) > 4096) return Result<uint, string>.Err("Use text of at most 4096 bytes.");
        uint count = 0;
        bool inWord = false;
        foreach (char scalar in text) {
            bool word = !Text.Whitespace(scalar);
            if (word && !inWord) ++count;
            inWord = word;
        }
        return Result<uint, string>.Ok(count);
    }
}
// lsf-example-end: capsule

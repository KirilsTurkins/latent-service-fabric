using System.Collections.Generic;
using ServiceWorld;
using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.http.IClientImports;
namespace ServiceWorld.wit.Exports.examples.httpStatus;

public class ApiExportsImpl : IApiExports
{
    public static Result<ushort, Raw.HttpError> Check(string url)
    {
        var response = Http.Send(new Raw.Request(
            Raw.Method.GET, url, new List<Raw.Header>(), null, null, null, 5000));
        return response.IsOk ? Result<ushort, Raw.HttpError>.Ok(response.AsOk.status)
            : Result<ushort, Raw.HttpError>.Err(response.AsErr);
    }
}

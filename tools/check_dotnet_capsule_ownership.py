"""Execute deterministic C# owner misuse tests without guest or provider claims."""
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json
from tools.rust_capsule_build import Commands


def check(output, environment):
    output = fresh(output)
    sdk = ROOT / "sdk/dotnet-guest"
    for source, destination in (("tests/Ownership.csproj", "Ownership.csproj"), ("tests/Ownership.cs", "Checks.cs"),
            ("ownership/Owner.cs", "Owner.cs"), ("ownership/SecretBytes.cs", "SecretBytes.cs"),
            ("global.json", "global.json"), ("nuget.config", "nuget.config")):
        (output / destination).write_bytes(read_file(sdk / source))
    environment = dict(environment, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
        DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", DOTNET_ROLL_FORWARD="Disable",
        DOTNET_CLI_HOME=str(output / "cli-home"), MSBUILDDISABLENODEREUSE="1")
    commands = Commands(output, output, environment)
    if commands.run("dotnet-version", "dotnet", "--version").strip() != b"10.0.100":
        raise ValueError("pinned .NET SDK required for ownership tests")
    result = commands.run("owners", "dotnet", "run", "--project", output / "Ownership.csproj", "--configuration", "Release")
    if b"C# ownership tests passed: 7" not in result:
        raise ValueError("incomplete C# ownership tests")
    report = {"status": "passed", "cases": 7, "commands": commands.records}
    write_json(output / "ownership.json", report)
    return report

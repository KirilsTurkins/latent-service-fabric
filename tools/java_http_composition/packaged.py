"""Finite Java execution using authenticated packages and genuine workspaces.

The conductor is source tooling. All frontend, helper, compiler and node code
comes from the independently approved publisher archives. Fresh build receipts
remain distinct from the retained C4 campaign and never establish signing trust.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.build_process import run_bounded_result
from tools.dev_packaged_process import digest as file_digest
from tools.dev_packaged_process import write_json as replace_public
from tools.dev_packaged_windows import Frontend, acquire, inputs
from tools.dev_workflow import build, project, state, tool_inventory
from tools.dev_workflow.common import digest, encode, require
from tools.java_http_composition import context, inspection, provider_timeout, resource_diagnostics
from tools.java_http_composition.build import projects
from tools.java_http_composition.node import (
    SERVICE_CAPABILITY, TENANT, configure, grant, idle, invoke, rebind, route, service_grant,
)
from tools.java_http_composition.preflight import NativeFrontend
from tools.java_http_composition.qualify import fresh_status, publish
from tools.phase2_operator_process import read_json, write_json
from tools.phase2_operator_scenario import TOKEN
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, deploy
from tools.rust_capsule_project import ROOT, fresh
from tools.run_security_profile_workflow import replace_config
from tools.sdk_provider_scenario import close_failed_provider, start_provider


def _sources(output):
    observed = run_bounded_result(["git", "rev-parse", "HEAD"], cwd=ROOT,
        env=build_environment(output), timeout_seconds=10, max_output_bytes=2048)
    require(observed.returncode == 0, "packaged-java-original-conductor-checkout-required")
    result = {"checkout": observed.stdout.decode("ascii").strip(), "runtimeSources": source_identity(ROOT)}
    for key, name in (("fixture", "examples/java-http-composition"), ("javaSdk", "sdk/java-guest"),
                      ("wit", "wit/platform"), ("helpers", "tools/java_http_composition"),
                      ("generator", "tools/java_http_generation"), ("compositionProbe", "tools/composition_probe")):
        result[key] = inventory(ROOT / name)
    result["entrypoint"] = file_identity(ROOT / "tools/qualify_packaged_java_composition.py")
    result["workflow"] = file_identity(ROOT / ".github/workflows/developer-packaged-qualification.yml")
    return result


def _compiler_logs(roots, output):
    destination = output / "compiler-logs"
    total, count, retained = 0, 0, []
    for workspace, root in roots.items():
        for pattern in ("*/source/build-cache/compiler-*.log", "*/source/output/compiler-logs/*",
                        "*/source/output/*FAILED*.json"):
            for original in sorted((root / "builds").glob(pattern)):
                require(original.resolve().is_relative_to((root / "builds").resolve())
                    and original.is_file() and not original.is_symlink(), "packaged-java-original-compiler-log-owner")
                size = original.stat().st_size
                count += 1
                total += size
                require(count <= 128 and size <= 4 * 1024 * 1024 and total <= 16 * 1024 * 1024,
                        "packaged-java-original-compiler-log-bound")
                name = workspace + "/" + original.relative_to(root / "builds").as_posix()
                target = destination / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(original, target)
                retained.append({"path": name, **file_identity(target, 4 * 1024 * 1024)})
    return retained


def _connect(api, frontend, workspace):
    import pwd
    backend = api.root / (workspace + "-backend.json")
    write_json(backend, {"kind": "linux", "python": sys.executable,
        "helper": str(frontend.binary.parents[1] / "helper.pyz"),
        "helperSha256": file_digest(frontend.binary.parents[1] / "helper.pyz")})
    api.call("connect", "--workspace", workspace, "--backend-config", backend)
    home = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    root = home / ".lsf-dev" / workspace
    require(root.is_dir() and not root.is_symlink(), "packaged-composition-real-workspace-required")
    return root


def _install(api, configuration, workspace, index):
    runtime, _tools = inputs(api, configuration, "java", index)
    selected = api.root / (workspace + "-runtime.json")
    write_json(selected, read_json(runtime))
    api.call("install", "--workspace", workspace, "--runtime-inputs", selected, timeout=1200)


def _build(api, configuration, workspace, root, output, observation, *, diagnostics=False):
    tools = api.root / "java-tools.json"
    installed = api.call("install-tools", "--workspace", workspace, "--tool-inputs", tools, timeout=1800)
    require(installed["publisherAuthenticated"] is True
        and installed["sourceCommit"] == configuration["sourceCommit"], "packaged-java-original-tools-required")
    cached = acquire(api, configuration, configuration["artifacts"]["java"], "linux-x86_64")
    template_root = api.state / "bundles" / cached["bundle"]
    template = read_json(template_root / "templates.json")["templates"]["greeting"]
    template_manifest = read_json(template_root / template["path"] / "template.json")
    template_identity = digest(encode(template_manifest))
    report = observation["freshBuilds"] = {"publisherTools": installed,
        "templateIdentity": template_identity, "buildReceipts": {}, "runtimeRebuilt": False}
    relative = Path(template["path"]).relative_to("templates").as_posix()
    authored = projects(output / "source-projects")
    if diagnostics:
        # These are new inputs to the actual compiler. Never relabel them as
        # the original C4 component or the unadapted hosted campaign.
        report["diagnosticFixtureAdaptations"] = {
            "domain": provider_timeout.adapt_domain(authored["domain"]),
            **{name: provider_timeout.adapt_adapter(authored[name]) for name in ("adapter", "adapter-next")}}
    selected, receipts = {}, {}
    (output / "projects").mkdir(mode=0o700)
    (output / "builds").mkdir(mode=0o700)
    for name, capsule_project in authored.items():
        source = output / "projects" / name
        api.call("init", source, "--bundle", cached["bundle"], "--template", relative,
                 "--template-sha256", template_identity)
        # This is a new, owned authoring project. Preserve the authenticated
        # template's compiler recipe and tool pins while editing actual source.
        app = source / "app"
        require(app.resolve().is_relative_to((output / "projects").resolve())
            and app.is_dir() and not app.is_symlink(), "packaged-java-owned-source-required")
        shutil.rmtree(app)
        shutil.copytree(capsule_project, app, symlinks=False)
        owner = read_json(app / "capsule-project.json")
        descriptor = read_json(source / "latent.project.json")
        descriptor.update({key: owner[key] for key in ("name", "tenant", "service")})
        project.validate(descriptor)
        replace_public(source / "latent.project.json", descriptor)
        api.call("trust", "--workspace", workspace, "--project", source)
        actual = api.call("build", "--workspace", workspace, "--project", source, timeout=1200)
        built_source, receipt = build.accepted(root, state.load(root, "project.json"))
        require(actual == receipt, "packaged-java-original-build-receipt-required")
        selected[name] = built_source / descriptor["build"]["outputRoot"]
        receipts[name] = deepcopy(receipt)
        report["buildReceipts"][name] = deepcopy(receipt)
        public = output / "builds" / name
        public.mkdir(mode=0o700)
        for filename in ("BUILD-COMPLETE.json", "contracts.json", "surface.json", "build-observation.json"):
            original = selected[name] / filename
            require(original.is_file() and not original.is_symlink()
                and original.stat().st_size <= 1024 * 1024, "packaged-java-original-public-build-bound")
            shutil.copyfile(original, public / filename)
        replace_public(output / "observation.json", observation)
    require(len({row["artifacts"]["component"] for row in receipts.values()}) == 4,
            "packaged-java-independently-built-component-identities")
    last = state.load(root, "project.json")["descriptor"]
    tools_root = Path(installed["directory"])
    inventory = tool_inventory.check(tools_root, last, "linux-x86_64")
    signer = next(row for row in last["build"]["tools"] if row["name"] == "test-signer")
    require(file_digest(tools_root / signer["path"]) == signer["sha256"], "packaged-java-pinned-signer-required")
    (output / "signing").mkdir(mode=0o700)
    commands = Commands(ROOT, output / "signing", build_environment(output / "signing"))
    commands.run("original-demo-sign-separated", tools_root / signer["path"], "demo-sign-separated",
                 output / "releases", *selected.values())
    require(tool_inventory.check(tools_root, last, "linux-x86_64") == inventory,
            "packaged-java-original-tool-inventory-changed")
    report.update(releaseSet=read_json(output / "releases/release-set.json"),
                  signer=file_identity(tools_root / signer["path"]))
    return report


def _configure(root, releases, output, *, former, provider_port=None):
    original = read_json(root / "runtime/config/node.json")
    output.mkdir(mode=0o700)
    prototype, host = configure(output, releases, http=not former, former_profile=former)
    selected = read_json(prototype)
    for key in ("nodeId", "bind", "dataDirectory", "securityProfile"):
        selected[key] = original[key]
    selected["credentials"] = [*original["credentials"], *selected["credentials"]]
    selected["supplyChain"]["policyFile"] = str(releases / "policy.json")
    config = root / "runtime/config/node.json"
    require(not (root / "control.sock").exists(), "packaged-java-configure-only-stopped-node")
    if provider_port is not None:
        # Protected credential paths resolve relative to the real installed
        # config directory, not the conductor's observation directory.
        selected = provider_timeout.configure(config.parent, selected, provider_port)
        require(len(selected["cells"]) == 1 and selected["cells"][0]["queueCapacity"] == 4,
                "packaged-java-original-fixture-queue-bound")
        # Narrow only this disposable diagnostic fixture. One waiting root plus
        # the real parent and child exhausts admission without a larger load.
        selected["cells"][0]["queueCapacity"] = resource_diagnostics.QUEUE_SIZE
    replace_config(config, selected)
    return config, host, {"originalConfigurationDigest": digest(encode(original)),
        "selectedConfigurationDigest": digest(encode(selected)), "nodeId": original["nodeId"],
        "installerScopePreserved": True, "profile": selected["securityProfile"],
        "bounds": {key: selected[key] for key in ("cells", "execution", "limits", "budgetProfile")}}


def _client(root, ready, directory, cancellation, deadline):
    from tools.dev_workflow.helper import installation
    _layout, current = installation(root)
    directory.mkdir(mode=0o700)
    config = read_json(root / "runtime/config/node.json")
    client = RecordingClient(current / "bin/latent", directory, cancellation, min(deadline, time.monotonic() + 900),
                             evidence=directory / "controls", invocation_timeout_millis=120000)
    client.node_id = config["nodeId"]
    settings = directory / "operator.json"
    write_json(settings, {"formatVersion": 1, "defaultProfile": "operator", "profiles": [{
        "name": "operator", "endpoint": "http://" + config["bind"], "tenant": TENANT,
        "token": TOKEN, "connectTimeoutMillis": 2000, "rpcTimeoutMillis": 15000}]})
    client.config = settings
    observed = client.call("node", "get", client.node_id)["data"]["inventory"]
    require(observed["health"]["ready"] and ready["state"] == "ready", "packaged-java-actual-node-readiness")
    return client, SimpleNamespace(startup_record={"providers": ready["providers"]})


def _schedules(frontend, api, workspace, client, releases, output, snapshots, config, *, former):
    results = {}
    for mode in ("standalone", "workspace"):
        schedule, result = frontend.schedule(client, releases, output / ("preflight-" + mode),
            snapshots, config, former=former,
            state_root=api.state if mode == "workspace" else None,
            workspace=workspace if mode == "workspace" else None)
        if former:
            result["formerProfile"] = schedule.former_profile(mode=mode)
        else:
            result["current"] = schedule.current(mode=mode)
            result["negatives"] = schedule.negatives(mode=mode)
        results[mode] = (schedule, result)
    return results


def _former(frontend, api, workspace, root, output, releases, cancellation, *, provider_port=None):
    config, _host, configuration = _configure(root, releases, output / "configuration", former=True,
                                             provider_port=provider_port)
    ready = api.start(workspace)
    client, node = _client(root, ready, output / "client", cancellation, api.deadline)
    publications = publish(client, releases)
    extra = () if provider_port is None else (provider_timeout.grant(client, node, publications["domain"], provider_port),)
    targets = grant(client, node, releases, publications, domain_grants=extra)
    failure = invoke(client, targets, "domain", "status", [], "java-former-http-profile", codes=(4,))
    require(failure["error"]["code"] == "resource-exhausted", "packaged-java-former-profile-original-failure")
    tree = context.tree(client, "java-former-http-profile")
    diagnostic = tree["nodes"][0]["diagnostic"]
    require(diagnostic["stage"] == 3 and diagnostic["reason"] == 1
        and "activation.diagnostic.v1" not in str(failure), "packaged-java-former-profile-authorized-diagnosis")
    original = inspection.observe(client, "domain", publication=publications["domain"], expected=1)
    require(original["candidates"][0]["preparation"]["stateName"] == "rejected",
            "packaged-java-former-profile-real-preparation-rejected")
    schedules = _schedules(frontend, api, workspace, client, releases, output,
                          {"domain": original}, config, former=True)
    result = {"configuration": configuration, "failure": failure, "authorizedTree": tree,
            "targetInspection": original, "preflight": {mode: result for mode, (_schedule, result) in schedules.items()},
            "idle": idle(client), "down": api.down(workspace)}
    if provider_port is not None:
        result["providerPhysicalShutdown"] = provider_timeout.verify_managed_shutdown(result["down"])
    return result


def _current(frontend, api, workspace, root, output, releases, cancellation, *, provider_port=None, provider_control=None):
    config, host, configuration = _configure(root, releases, output / "configuration", former=False,
                                            provider_port=provider_port)
    ready = api.start(workspace)
    client, node = _client(root, ready, output / "client", cancellation, api.deadline)
    publications = publish(client, releases)
    extra = () if provider_port is None else (provider_timeout.grant(client, node, publications["domain"], provider_port),)
    targets = grant(client, node, releases, publications, domain_grants=extra)
    route(client, host, publications["adapter"])
    missing = context.capture_http(client, host, expected=(403,))
    generation = service_grant(client, node, publications)
    targets["adapter"] = deploy(client, releases / "java-http-adapter/deployment.json", publications["adapter"],
        generation=str(targets["adapter"]["generation"]), grants=targets["adapter"]["grants"] + [
            {"capability": SERVICE_CAPABILITY, "policy": "java-domain-allow"}])
    route(client, host, publications["adapter"])
    snapshots = {name: inspection.selected(client, releases, publications, name) for name in ("domain", "adapter")}
    authority = inspection.authority(client)
    ordinary = inspection.ordinary_http_binding(client, host, snapshots["domain"])
    schedules = _schedules(frontend, api, workspace, client, releases, output, snapshots, config, former=False)
    # The ordinary context capsule retains only its actual installed clocks and
    # original signed resource declaration. The domain's new HTTP capability
    # is not a grant for this independent publication.
    context_targets = targets if provider_port is None else {**targets, "domain": {**targets["domain"],
        "grants": [row for row in targets["domain"]["grants"] if row["capability"] != provider_timeout.CAPABILITY],
        "budget": read_json(releases / "java-http-context-required/deployment.json")["spec"]["resources"]}}
    result = {"configuration": configuration, "missingGrant": missing, "targetInspection": snapshots,
        "authority": authority, "ordinaryHttpBinding": ordinary,
        "freshComposedExecution": fresh_status(client, targets, host, "java-packaged-fresh-success"),
        "ordinaryContext": context.ordinary_import(client, context_targets, releases, publications, host)}
    if provider_port is not None:
        result["childFuel"] = resource_diagnostics.fuel(client, targets, host)
        result["queuePressure"] = resource_diagnostics.queue(client, targets, host)
        result["providerTimeout"] = provider_timeout.qualify(client, host, provider_control, provider_port)
    # A reviewed policy revision invalidates the original binding plan even
    # after restoration. Retain that intent, then explicitly redeploy/rebind.
    from tools.static_api.node import policy
    generation = policy(client, "policy", "java-domain-allow", {"formatVersion": 1, "tenant": TENANT,
                                                               "rules": []}, generation)["generation"]
    result["revokedHttp"] = context.capture_http(client, host, expected=(403, 409, 503))
    for mode, (schedule, receipt) in schedules.items():
        receipt["changedAuthority"] = schedule.changed_authority(mode=mode)
    generation = service_grant(client, node, publications, generation=generation)
    result["restoredOriginalPlanStale"] = inspection.stale_policy(client, "adapter", snapshots["adapter"])
    result["explicitNewDeployment"] = rebind(client, targets, releases, publications)
    route(client, host, publications["adapter"])
    result["afterExplicitRebind"] = fresh_status(client, targets, host, "java-packaged-after-rebind")
    result["preflight"] = {mode: receipt for mode, (_schedule, receipt) in schedules.items()}
    result["idle"] = idle(client)
    result["down"] = api.down(workspace)
    if provider_port is not None:
        result["providerPhysicalShutdown"] = provider_timeout.verify_managed_shutdown(result["down"])
    return result


def qualify(configuration, output, *, diagnostics=False):
    require(type(diagnostics) is bool, "packaged-java-explicit-diagnostic-campaign")
    require(sys.platform == "linux" and os.geteuid() != 0 and sys.version_info[:3] == (3, 13, 5),
            "packaged-java-unprivileged-pinned-linux-conductor-required")
    require(configuration["independentPolicyApproved"] is True
        and configuration["consentProvisionAndInstall"] is True, "packaged-java-independent-approval-required")
    output = fresh(output)
    report = {"schemaVersion": "latent.dev.packaged-java-composition.v1", "passed": False,
        "approvedProducerSource": configuration["sourceCommit"], "conductorSource": _sources(output),
        "freshJavaBuild": True, "retainedC4ArtifactsReused": False, "nativeRuntimeRebuilt": False,
        "diagnosticCampaignRequested": diagnostics, "diagnosticCampaignPassed": False,
        "commands": [], "cleanup": {}, "bounds": {"commands": 360, "componentBuilds": 4,
        "liveNodes": 1, "nodeCampaignSeconds": 900, "conductorSeconds": 7200}}
    api = None
    peer = None
    workspaces = {}
    try:
        frontend = NativeFrontend.authenticate_release(configuration, output / "authenticated-frontend")
        report["frontend"] = frontend.observation
        control = output / "controller"
        control.mkdir(mode=0o700)
        api = Frontend(frontend.binary, control, report)
        baseline = "test-java-composition-710"
        root = _connect(api, frontend, baseline)
        workspaces[baseline] = root
        _install(api, configuration, baseline, 10)
        _build(api, configuration, baseline, root, output, report, diagnostics=diagnostics)
        releases = output / "releases"
        former = "test-java-former-profile-710"
        former_root = _connect(api, frontend, former)
        workspaces[former] = former_root
        _install(api, configuration, former, 11)
        with owned_cancellation() as cancellation:
            provider_control, provider_port = None, None
            if diagnostics:
                provider_control = output / "provider-peer"
                provider_control.mkdir(mode=0o700)
                owner = SimpleNamespace(deadline=api.deadline, environment=api.env, cancellation=cancellation)
                peer, provider_port = start_provider(owner, provider_control, maximum_seconds=1200)
                report["providerPeer"] = {"port": provider_port, "maximumSeconds": 1200}
            report["formerProfile"] = _former(frontend, api, former, former_root,
                fresh(output / "former-profile"), releases, cancellation, provider_port=provider_port)
            report["currentProfile"] = _current(frontend, api, baseline, root,
                fresh(output / "current-profile"), releases, cancellation,
                provider_port=provider_port, provider_control=provider_control)
            if peer is not None:
                report["providerPeer"]["shutdown"] = provider_timeout.stop_peer(peer)
                peer = None
                report["diagnosticCampaignPassed"] = all(report["currentProfile"][name]["status"] == "passed"
                    for name in ("childFuel", "queuePressure", "providerTimeout"))
        frontend.unchanged()
        require(report["conductorSource"] == _sources(output), "packaged-java-conductor-source-changed")
        report["passed"] = True
    except BaseException as error:
        report["failure"] = getattr(error, "code", str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__)
        raise
    finally:
        try:
            report["originalCompilerLogs"] = _compiler_logs(workspaces, output)
        except BaseException as error:
            report["compilerLogRetentionFailure"] = type(error).__name__
            report["passed"] = False
        if api is not None:
            for workspace in list(api.running):
                try:
                    report["cleanup"][workspace] = api.down(workspace)
                except BaseException as error:
                    report["cleanup"][workspace] = {"failure": type(error).__name__, "terminationConfirmed": False}
                    report["passed"] = False
        if peer is not None:
            report["cleanup"]["providerPeer"] = close_failed_provider(peer)
            report["passed"] = False
        replace_public(output / "observation.json", report)
    require(report["passed"], "packaged-java-qualification-or-cleanup-failed")
    return report

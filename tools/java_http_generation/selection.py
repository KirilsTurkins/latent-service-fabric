"""Closed explicit route selection against authoritative typed WIT."""
import re

PROFILE = "latent.java-http.adapter.v1"


def selected(surface: dict, selection: dict) -> list[dict]:
    if (not isinstance(selection, dict) or set(selection) != {"profile", "adapterName", "domain", "privateOperations", "routes"}
            or selection["profile"] != PROFILE):
        raise ValueError("route-selection: unsupported closed adapter selection")
    name, domain, routes = selection["adapterName"], selection["domain"], selection["routes"]
    if not isinstance(name, str) or len(name) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name):
        raise ValueError("route-selection: adapterName must be bounded lowercase kebab-case")
    if not isinstance(domain, dict) or set(domain) != {"service", "contract", "route"}:
        raise ValueError("route-selection: explicit service, contract and pinned route required")
    for key, maximum in (("service", 256), ("contract", 256), ("route", 128)):
        value = domain[key]
        if not isinstance(value, str) or not 0 < len(value) <= maximum or not re.fullmatch(r"[A-Za-z0-9:/@.+_-]+", value):
            raise ValueError("route-selection: invalid bounded " + key)
    exported = surface["exports"].get(domain["contract"])
    if exported is None or not exported["functions"]:
        raise ValueError("route-selection: contract is not an actual nonempty domain export")
    private = selection["privateOperations"]
    if (not isinstance(private, list) or len(private) > 64 or not all(isinstance(name, str) and name in exported["functions"] for name in private)
            or len(private) != len(set(private))):
        raise ValueError("route-selection: privateOperations must explicitly name distinct actual exports")
    if not isinstance(routes, list) or not 1 <= len(routes) <= 64:
        raise ValueError("route-selection: explicitly select one to 64 public operations")
    identities, client_names, result = set(), set(), []
    for route in routes:
        required = {"path", "method", "operation", "clientName"}
        if not isinstance(route, dict) or not required <= set(route) or set(route) - required - {"childDeadlineOffsetMillis"}:
            raise ValueError("route-selection: each public route requires path, method, operation and clientName")
        if "childDeadlineOffsetMillis" in route:
            offset = route["childDeadlineOffsetMillis"]
            if type(offset) is not int or not 0 <= offset <= 60000:
                raise ValueError("route-selection: childDeadlineOffsetMillis must be an integer from zero to 60000")
        path, method, operation, client = (route[key] for key in ("path", "method", "operation", "clientName"))
        if not isinstance(path, str) or len(path) > 256 or not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+", path):
            raise ValueError("route-selection: only bounded literal paths are supported")
        if method not in ("GET", "POST") or not isinstance(operation, str) or operation not in exported["functions"]:
            raise ValueError("route-selection: select an exported operation and GET or POST explicitly")
        function = exported["functions"][operation]
        if operation in private:
            raise ValueError("route-selection: private operation cannot become a public route")
        if function["kind"] not in ("freestanding", "async-freestanding"):
            raise ValueError("route-selection: resource operations cannot become HTTP routes")
        if method == "GET" and function["params"]:
            raise ValueError("route-selection: GET operations cannot require typed parameters; use POST")
        if (not isinstance(client, str) or not re.fullmatch(r"[a-z][A-Za-z0-9]*", client)
                or len(client) > 64 or client in {"constructor", "call", "origin", "schema", "then"}):
            raise ValueError("route-selection: invalid or reserved client method name")
        identity = (method, path)
        if identity in identities or client in client_names:
            raise ValueError("route-selection: duplicate route or client name")
        identities.add(identity)
        client_names.add(client)
        result.append({**route, "signature": function})
    return sorted(result, key=lambda item: (item["path"], item["method"]))

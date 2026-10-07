"""Closed native-produced TLS fixture input; no signing, listener or authority."""
from pathlib import Path
import re
import ssl
import stat

from tools.rust_capsule_project import read_file
from .inputs import decode, digest, require
from .provider import private_write

FILES = {"ca.der", "key.pem", "server.pem"}


def producer_bridge(args, review, fixture):
    if "reviewedTlsProducerBridge" not in review:
        require(fixture["producerNativeSource"] == args.native_source_commit,
                "closed-reviewed-native-tls-fixture")
        return
    bridge = review["reviewedTlsProducerBridge"]
    require(isinstance(bridge, dict) and set(bridge) == {
        "producerNativeSource", "producerConductorSource", "selectedNativeSource", "producerTool", "originReceipt", "files"}
        and bridge["producerNativeSource"] == fixture["producerNativeSource"]
        and isinstance(bridge["producerConductorSource"], str)
        and re.fullmatch(r"[0-9a-f]{40}", bridge["producerConductorSource"])
        and bridge["selectedNativeSource"] == args.native_source_commit == review.get("nativeSource")
        and bridge["producerNativeSource"] != bridge["selectedNativeSource"]
        and bridge["files"] == fixture["files"], "closed-reviewed-tls-producer-bridge")
    tool = bridge["producerTool"]
    require(isinstance(tool, dict) and set(tool) == {"name", "digest", "size"}
            and tool["name"] == "signer" and isinstance(tool["digest"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", tool["digest"])
            and type(tool["size"]) is int and 0 < tool["size"] <= 1073741824,
            "closed-reviewed-tls-producer-tool")
    row = bridge["originReceipt"]
    require(isinstance(row, dict) and set(row) == {"file", "bytes", "digest"}
            and row["file"] == "tls-producer-receipt.json"
            and type(row["bytes"]) is int and 0 < row["bytes"] <= 262144,
            "closed-reviewed-tls-origin-receipt")
    path = args.reviewed_policy_environment.parent / row["file"]
    observed = path.lstat()
    require(stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1 and not path.is_symlink(),
            "reviewed-tls-origin-refuses-links")
    raw = read_file(path, 262144)
    require(len(raw) == row["bytes"] and digest(raw) == row["digest"],
            "reviewed-tls-origin-byte-drift")
    origin = decode(raw, 262144)
    require(isinstance(origin, dict)
            and origin.get("schemaVersion") == "latent.java-transaction.focused-native.v1"
            and origin.get("nativeSourceCommit") == bridge["producerNativeSource"]
            and origin.get("conductorSourceCommit") == bridge["producerConductorSource"]
            and isinstance(origin.get("nativeTools"), dict)
            and origin["nativeTools"].get("signer") == tool,
            "reviewed-tls-origin-producer-drift")


def selected(args, review):
    value = None if review is None else review.get("reviewedTlsFixture")
    if value is None:
        require(review is None or "reviewedTlsProducerBridge" not in review,
                "reviewed-tls-bridge-requires-fixture")
        return None
    require(isinstance(value, dict) and set(value) == {"directory", "producerNativeSource", "files"}
            and value["directory"] == "tls-fixture"
            and isinstance(value["producerNativeSource"], str)
            and re.fullmatch(r"[0-9a-f]{40}", value["producerNativeSource"])
            and isinstance(value["files"], list) and len(value["files"]) == 3,
            "closed-reviewed-native-tls-fixture")
    producer_bridge(args, review, value)
    folder = args.reviewed_policy_environment.parent / value["directory"]
    require(folder.is_dir() and not folder.is_symlink() and {p.name for p in folder.iterdir()} == FILES,
            "closed-reviewed-tls-directory")
    retained = {}
    for row in value["files"]:
        require(isinstance(row, dict) and set(row) == {"file", "bytes", "digest"}
                and row["file"] in FILES and row["file"] not in retained
                and type(row["bytes"]) is int and 0 < row["bytes"] <= 65536,
                "closed-reviewed-tls-file")
        path = folder / row["file"]
        observed = path.lstat()
        require(stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1 and not path.is_symlink(),
                "reviewed-tls-refuses-links")
        raw = read_file(path, 65536)
        require(len(raw) == row["bytes"] and digest(raw) == row["digest"], "reviewed-tls-byte-drift")
        retained[row["file"]] = raw
    require(set(retained) == FILES and sum(map(len, retained.values())) <= 196608,
            "original-reviewed-tls-byte-bound")
    return value, retained


def certificate_validity(directory, ca):
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(str(directory / "server.pem"), str(directory / "key.pem"))
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.check_hostname = True
    client.verify_mode = ssl.CERT_REQUIRED
    client.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(ca))
    incoming_server, outgoing_server = ssl.MemoryBIO(), ssl.MemoryBIO()
    incoming_client, outgoing_client = ssl.MemoryBIO(), ssl.MemoryBIO()
    left = server.wrap_bio(incoming_server, outgoing_server, server_side=True)
    right = client.wrap_bio(incoming_client, outgoing_client, server_hostname="localhost")
    done = [False, False]
    consumed = 0
    for _ in range(16):
        for index, peer in enumerate((left, right)):
            if not done[index]:
                try:
                    peer.do_handshake()
                    done[index] = True
                except ssl.SSLWantReadError:
                    pass
        for output, incoming in ((outgoing_server, incoming_client), (outgoing_client, incoming_server)):
            data = output.read(65537)
            consumed += len(data)
            require(len(data) <= 65536 and consumed <= 262144, "reviewed-tls-handshake-byte-bound")
            if data:
                incoming.write(data)
        if all(done):
            break
    require(all(done) and ("DNS", "localhost") in right.getpeercert().get("subjectAltName", ()),
            "reviewed-tls-current-validity-and-san")


def copy(args, review, destination: Path):
    chosen = selected(args, review)
    if chosen is None:
        return False
    require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(),
            "fresh-reviewed-tls-destination")
    destination.mkdir(mode=0o700)
    for name, raw in chosen[1].items():
        private_write(destination / name, raw)
    certificate_validity(destination, chosen[1]["ca.der"])
    require(all(digest(read_file(destination / row["file"], 65536)) == row["digest"]
                for row in chosen[0]["files"]), "reviewed-tls-copy-byte-drift")
    return True

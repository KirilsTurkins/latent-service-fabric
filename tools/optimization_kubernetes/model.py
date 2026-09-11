"""Pure fixed #112 workload metadata and owned Kubernetes manifest builders."""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from tools.optimization_docker import model as docker
from tools.optimization_evidence.common import require

PREFIX = "latent.optimization.kubernetes-"
CLIENT_PREFIX = docker.CLIENT_PREFIX
DENSITIES = docker.DENSITIES
SERVICES = docker.SERVICES
TENANT, CONTRACT, TOKEN = docker.TENANT, docker.CONTRACT, docker.TOKEN
MAX_TOTAL_BYTES = docker.MAX_TOTAL_BYTES
MAX_FILE_BYTES = docker.MAX_FILE_BYTES
MAX_CLIENT_BYTES = docker.MAX_CLIENT_BYTES
MAX_HELPER_BYTES = docker.MAX_HELPER_BYTES
MAX_FILES = docker.MAX_FILES
HOST_ROOT = "/var/local/lsf112"
OWNER_LABEL = "latent.benchmark.owner"
RUN_LABEL = "latent.benchmark.run"
ROLE_LABEL = "latent.benchmark.role"
WORKER_LABEL = "latent.benchmark.worker"
POD_PIDS_LIMIT = 512
TERMINATION_SECONDS = 40
TMP_BYTES = 16 * 1024**2

repetitions = docker.repetitions
groups = docker.groups
phases = docker.phases


def _label(value, reason, maximum=63):
    require(isinstance(value, str) and 1 <= len(value) <= maximum
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", value) is not None, reason)
    return value


def _number(value, low, high, reason):
    require(type(value) is int and low <= value <= high, reason)
    return value


def namespace_name(owner, run_id):
    _label(owner, "kubernetes-owner", 48)
    _label(run_id, "kubernetes-run-id", 24)
    return _label(owner + "-" + run_id, "kubernetes-namespace-length")


def labels(owner, run_id, role=None):
    namespace_name(owner, run_id)
    value = {OWNER_LABEL: owner, RUN_LABEL: run_id}
    if role is not None:
        value[ROLE_LABEL] = _label(role, "kubernetes-role")
    return value


def namespace(owner, run_id):
    return {"apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": namespace_name(owner, run_id), "labels": labels(owner, run_id)}}


def host_path(owner, run_id, relative=None):
    """Name only an owned worker path; the parent verifies actual directories."""
    namespace_name(owner, run_id)
    base = HOST_ROOT + "/" + owner + "/" + run_id
    if relative is None:
        return base
    require(isinstance(relative, str) and 1 <= len(relative) <= 2048
            and all(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part) is not None
                    and part not in (".", "..") for part in relative.split("/")),
            "kubernetes-host-path-relative")
    return base + "/" + relative


def _owned_path(value, owner, run_id):
    require(isinstance(value, str) and len(value) <= 4096, "kubernetes-host-path")
    base = host_path(owner, run_id) + "/"
    require(value.startswith(base), "kubernetes-host-path-owner")
    require(host_path(owner, run_id, value[len(base):]) == value, "kubernetes-host-path-canonical")
    return value


def resources(arm, density=1):
    """CPU/memory match the Docker cohort; PID/FD controls are observed separately."""
    controls = docker.resources(arm, density)
    limits = {"cpu": str(controls["cpu_quota"] * 1000 // controls["cpu_period"]) + "m",
              "memory": str(controls["memory"] // 1024**2) + "Mi"}
    return {"requests": dict(limits), "limits": dict(limits)}


def startup_probe():
    return {"tcpSocket": {"port": 7070}, "initialDelaySeconds": 0, "periodSeconds": 1,
            "timeoutSeconds": 1, "failureThreshold": 120, "successThreshold": 1}


def plan(profile, *, owner):
    _label(owner, "kubernetes-owner", 48)
    workload = docker.plan(profile)
    return {"schema": PREFIX + "plan.v1", "profile": profile, "workload": workload,
            "seed_reuse": {"source": "docker-stopped-pristine-catalogs", "densities": list(DENSITIES),
                           "new_lsf_starts": 0, "new_management_rpcs": 0, "new_guest_invokes": 0},
            "measured_services": 82 * workload["repetitions"],
            "maximum_live_application_pods": 32, "maximum_live_client_pods": 1,
            "node_selector": {WORKER_LABEL: owner}, "runtime": "runc", "runtime_class": None,
            "resources": "cpu-memory-requests-equal-limits-matched-aggregate",
            "pod_pids_limit": POD_PIDS_LIMIT, "fd_limit_policy": "observe-runtime-default",
            "restart_policy": "Never", "automount_service_account_token": False,
            "termination_grace_seconds": TERMINATION_SECONDS, "startup_probe": startup_probe(),
            "ongoing_readiness_probe": False, "liveness_probe": False,
            "tmp": {"medium": "Memory", "size_limit_bytes": str(TMP_BYTES),
                    "mount_flags": "retain-actual-no-docker-equivalence-assumption"},
            "service": {"type": "ClusterIP", "port": 7070, "target_port": 7070,
                        "session_affinity": "None", "publish_not_ready_addresses": False,
                        "ip_family": "IPv4"},
            "host_path_root": HOST_ROOT}


def application_role(pair, group, arm, index=0):
    _number(pair, 0, 6, "kubernetes-pair")
    _number(group, 0, 5, "kubernetes-group")
    require(arm in ("lsf", "native"), "kubernetes-application-arm")
    _number(index, 0, 31 if arm == "native" else 0, "kubernetes-application-index")
    return f"p{pair}-g{group}-{arm}-{index}"


def client_role(pair):
    return "client-p" + str(_number(pair, 0, 6, "kubernetes-pair"))


def service_name(pair, group, index):
    _number(pair, 0, 6, "kubernetes-pair")
    _number(group, 0, 5, "kubernetes-group")
    _number(index, 0, 31, "kubernetes-service-index")
    return f"p{pair}-g{group}-s{index}"


def _image(value, arm):
    # The parent binds this exact loaded tag to the retained #111 image graph.
    require(isinstance(value, str)
            and re.fullmatch(r"lsf111-images-[0-9a-f]{20}:" + arm, value) is not None,
            "kubernetes-original-image-tag")
    return value


def pod(image, command, *, arm, density, owner, run_id, role, fixtures, output, data=None):
    """Build one Pod; prepare/hash fresh host directories before submitting it."""
    selected_resources = resources(arm, density)
    _label(role, "kubernetes-role")
    _image(image, arm)
    require(isinstance(command, list) and 1 <= len(command) <= 32
            and all(isinstance(arg, str) and 1 <= len(arg) <= 4096
                    and not any(ord(char) < 32 or ord(char) == 127 for char in arg) for arg in command),
            "kubernetes-container-arguments")
    require((data is not None) == (arm == "lsf"), "kubernetes-application-data-mount")
    selected = [("fixtures", _owned_path(fixtures, owner, run_id), "/fixtures", True),
                ("output", _owned_path(output, owner, run_id), "/output", False)]
    if data is not None:
        selected.append(("data", _owned_path(data, owner, run_id), "/data", False))
    paths = [PurePosixPath(row[1]) for row in selected]
    require(all(not left.is_relative_to(right) and not right.is_relative_to(left)
                for index, left in enumerate(paths) for right in paths[index + 1:]),
            "kubernetes-overlapping-host-mounts")
    volumes = [{"name": name, "hostPath": {"path": path, "type": "Directory"}}
               for name, path, _, _ in selected]
    mounts = [{"name": name, "mountPath": destination, "readOnly": readonly}
              for name, _, destination, readonly in selected]
    volumes.append({"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}})
    mounts.append({"name": "tmp", "mountPath": "/tmp", "readOnly": False})
    container = {"name": arm, "image": image, "imagePullPolicy": "Never", "args": list(command),
                 "stdin": arm == "client", "stdinOnce": False, "tty": False,
                 "resources": selected_resources, "volumeMounts": mounts,
                 "securityContext": {"readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
                                     "privileged": False, "capabilities": {"drop": ["ALL"]}}}
    if arm != "client":
        container.update(ports=[{"name": "grpc", "containerPort": 7070, "protocol": "TCP"}],
                         startupProbe=startup_probe())
    return {"apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": role, "namespace": namespace_name(owner, run_id),
                         "labels": labels(owner, run_id, role)},
            "spec": {"containers": [container], "volumes": volumes,
                     "nodeSelector": {WORKER_LABEL: owner}, "restartPolicy": "Never",
                     "terminationGracePeriodSeconds": TERMINATION_SECONDS,
                     "automountServiceAccountToken": False, "enableServiceLinks": False,
                     "hostNetwork": False, "hostPID": False, "hostIPC": False,
                     "shareProcessNamespace": False, "dnsPolicy": "ClusterFirst"}}


def service(*, owner, run_id, pair, group, arm, density, index):
    require(type(density) is int and density in DENSITIES, "kubernetes-service-density")
    _number(index, 0, density - 1, "kubernetes-service-index")
    name = service_name(pair, group, index)
    pod_role = application_role(pair, group, arm, index if arm == "native" else 0)
    return {"apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": namespace_name(owner, run_id),
                         "labels": labels(owner, run_id, name),
                         "annotations": {"latent.benchmark.service": SERVICES[index]}},
            "spec": {"type": "ClusterIP", "selector": labels(owner, run_id, pod_role),
                     "ports": [{"name": "grpc", "port": 7070, "targetPort": 7070, "protocol": "TCP"}],
                     "sessionAffinity": "None", "publishNotReadyAddresses": False,
                     "ipFamilyPolicy": "SingleStack", "ipFamilies": ["IPv4"],
                     "internalTrafficPolicy": "Cluster"}}


def services(*, owner, run_id, pair, group, arm, density):
    require(type(density) is int and density in DENSITIES, "kubernetes-service-density")
    return [service(owner=owner, run_id=run_id, pair=pair, group=group, arm=arm, density=density, index=index)
            for index in range(density)]

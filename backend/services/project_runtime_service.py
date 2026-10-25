"""Docker-backed runner for authenticated, isolated student workspaces."""
import json
import os
import re
import secrets
import hashlib
import shlex
import shutil
import tempfile
import threading
import atexit
import httpx
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from database import get_supabase_client

MAX_FILES = int(os.getenv("PROJECT_RUNTIME_MAX_FILES", "200"))
MAX_BYTES = int(os.getenv("PROJECT_RUNTIME_MAX_BYTES", str(10_000_000)))
CPU_LIMIT = float(os.getenv("PROJECT_RUNTIME_CPU_LIMIT", "1"))
MEMORY_LIMIT = os.getenv("PROJECT_RUNTIME_MEMORY_LIMIT", "512m")
PROCESS_LIMIT = int(os.getenv("PROJECT_RUNTIME_PROCESS_LIMIT", "128"))
TIMEOUT = int(os.getenv("PROJECT_RUNTIME_TIMEOUT_SECONDS", "1800"))
PYTHON_IMAGE = os.getenv("PROJECT_RUNTIME_PYTHON_IMAGE", "python:3.12-slim")
NODE_IMAGE = os.getenv("PROJECT_RUNTIME_NODE_IMAGE", "node:22-alpine")
INSTALL_NETWORK = os.getenv("PROJECT_RUNTIME_INSTALL_NETWORK", "none").strip().casefold()
INSTALL_PROXY_CONTAINER = os.getenv("PROJECT_RUNTIME_INSTALL_PROXY_CONTAINER", "").strip()
INSTALL_PROXY_URL = os.getenv("PROJECT_RUNTIME_INSTALL_PROXY_URL", "").strip()
PREVIEW_PROXY_HOST = os.getenv("PROJECT_RUNTIME_PREVIEW_PROXY_HOST", "127.0.0.1")
CONTAINER_UID = int(os.getenv("PROJECT_RUNTIME_CONTAINER_UID", str(os.getuid() if hasattr(os, "getuid") else 1000)))
CONTAINER_GID = int(os.getenv("PROJECT_RUNTIME_CONTAINER_GID", str(os.getgid() if hasattr(os, "getgid") else 1000)))
_runs: dict[str, dict[str, Any]] = {}
_lock = threading.RLock()
INSTALL_LOG_LIMIT = 256 * 1024
INSTALL_STATUS_INTERVAL = 1.0


class RuntimeErrorBase(Exception):
    pass


def _persist_entry(entry: dict[str, Any]) -> None:
    """Persist lifecycle state without logs, source, credentials, or preview secrets."""
    try:
        row = {
            "owner_id": entry["owner_id"],
            "workspace_id": entry["workspace_id"],
            "container_id": entry.get("container_id"),
            "install_container_id": entry.get("install_container_id"),
            "install_network_name": entry.get("install_network_name"),
            "workspace_dir": entry.get("directory"),
            "runtime_type": entry.get("detection", {}).get("type"),
            "runtime_status": entry.get("status", "queued"),
            "created_at": entry.get("created_at"),
            "expires_at": datetime.fromtimestamp(entry.get("timeout_at", datetime.now(timezone.utc).timestamp() + TIMEOUT), timezone.utc).isoformat(),
            "preview_port": entry.get("preview_port"),
            "host_port": entry.get("host_port"),
            "network_name": entry.get("network_name"),
            "preview_token_hash": entry.get("preview_token_hash"),
            "preview_token_used": entry.get("preview_token_used", False),
            "error": entry.get("error"),
            "exit_code": entry.get("exit_code"),
        }
        result = get_supabase_client().table("project_runtime_sessions").upsert(
            row, on_conflict="owner_id,workspace_id"
        ).execute()
        if getattr(result, "error", None):
            raise RuntimeError("runtime metadata write failed")
    except Exception as exc:
        raise RuntimeErrorBase("Project runtime metadata storage is unavailable. Apply migration 0007 and verify backend database credentials.") from exc


def _read_entry(owner_id: str, workspace_id: str) -> dict[str, Any] | None:
    try:
        result = get_supabase_client().table("project_runtime_sessions").select("*").eq(
            "owner_id", owner_id
        ).eq("workspace_id", workspace_id).limit(1).execute()
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:
        raise RuntimeErrorBase("Project runtime metadata storage is unavailable. Apply migration 0007 and verify backend database credentials.") from exc


def _read_preview_entry(workspace_id: str, token_hash: str) -> dict[str, Any] | None:
    try:
        result = get_supabase_client().table("project_runtime_sessions").select("*").eq(
            "workspace_id", workspace_id
        ).eq("preview_token_hash", token_hash).limit(1).execute()
        rows = getattr(result, "data", None) or []
        return rows[0] if rows else None
    except Exception as exc:
        raise RuntimeErrorBase("Project runtime metadata storage is unavailable.") from exc


def normalize_manifest(files: dict[str, str]) -> dict[str, str]:
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ValueError(f"Workspace must contain between 1 and {MAX_FILES} files.")
    normalized: dict[str, str] = {}
    total = 0
    for raw_path, content in files.items():
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise ValueError("Workspace paths and file contents must be text.")
        path = PurePosixPath(raw_path.replace("\\", "/"))
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("Workspace contains an invalid file path.")
        safe_path = path.as_posix()
        base_name = path.name.casefold()
        if base_name.startswith(".env") or base_name in {"id_rsa", "id_ed25519", "credentials", "secrets.json"} or base_name.endswith((".pem", ".key", ".p12", ".pfx")):
            continue
        if safe_path.startswith("/") or re.match(r"^[A-Za-z]:", safe_path):
            raise ValueError("Workspace contains an invalid file path.")
        total += len(safe_path.encode()) + len(content.encode())
        if total > MAX_BYTES:
            raise ValueError("Workspace exceeds the project runtime size limit.")
        normalized[safe_path] = content
    if not normalized:
        raise ValueError("Workspace contains no runnable files after excluding environment and credential files.")
    return normalized


def detect_project(files: dict[str, str], working_directory: str = "") -> dict[str, Any]:
    files = normalize_manifest(files)
    cwd = PurePosixPath(working_directory or ".")
    if cwd.is_absolute() or any(part == ".." for part in cwd.parts):
        raise ValueError("Working directory must be a workspace-relative path.")
    prefix = "" if str(cwd) == "." else cwd.as_posix().rstrip("/") + "/"
    scoped = {p[len(prefix):]: c for p, c in files.items() if p.startswith(prefix)}
    if not scoped:
        raise ValueError("Working directory does not contain project files.")
    requirements = next((p for p in ("requirements.txt",) if p in scoped), None)
    package = scoped.get("package.json")
    pkg = None
    if package is not None:
        try:
            pkg = json.loads(package)
        except (ValueError, TypeError):
            raise ValueError("package.json is not valid JSON.") from None
        if not isinstance(pkg, dict):
            raise ValueError("package.json must contain a JSON object.")
    python_entries = [p for p in ("app.py", "main.py", "server.py") if p in scoped]
    node_entry = None
    node_script = None
    if pkg is not None:
        main = pkg.get("main")
        if isinstance(main, str) and main in scoped and main.endswith(".js"):
            node_entry = main
        elif "index.js" in scoped:
            node_entry = "index.js"
        scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        node_script = next((name for name in ("start", "dev") if isinstance(scripts.get(name), str)), None)
    if requirements and len(python_entries) == 1 and pkg is None:
        req_text = "\n".join(line.split("#", 1)[0] for line in scoped[requirements].splitlines()).casefold()
        framework = "flask" if re.search(r"(?m)^\s*flask(?:[<>=!~\[]|\s|$)", req_text) else None
        return {"type": "python", "entry": python_entries[0], "requirements": "requirements.txt", "framework": framework, "preview_port": 5000 if framework == "flask" else None, "working_directory": str(cwd)}
    if pkg is not None and (node_entry or node_script) and not requirements and not python_entries:
        dependencies = pkg.get("dependencies") if isinstance(pkg.get("dependencies"), dict) else {}
        dev_dependencies = pkg.get("devDependencies") if isinstance(pkg.get("devDependencies"), dict) else {}
        framework = "next" if "next" in dependencies or "next" in dev_dependencies else "vite" if "vite" in dependencies or "vite" in dev_dependencies else None
        return {"type": "node", "entry": node_entry, "script": node_script, "framework": framework, "preview_port": 3000 if node_script and (framework or node_script == "start") else None, "working_directory": str(cwd)}
    if requirements or python_entries or pkg is not None:
        raise ValueError("Project configuration is ambiguous or unsupported. Python projects need requirements.txt and one of app.py, main.py, server.py; Node projects need package.json with main and a JavaScript entry file.")
    raise ValueError("Unsupported project. No supported Python or Node project configuration was found.")


def _docker_client():
    try:
        import docker
        return docker.from_env()
    except Exception as exc:
        raise RuntimeErrorBase("Project runtime is unavailable. Configure Docker and install the backend Docker SDK.") from exc


def _write_manifest(root: Path, files: dict[str, str]) -> None:
    root_resolved = root.resolve()
    if os.name == "posix":
        root.chmod(0o770)
    for name, content in files.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root_resolved):
            raise ValueError("Workspace contains an invalid file path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if os.name == "posix":
            target.chmod(0o660)
            for directory in target.parents:
                if directory == root.parent:
                    break
                directory.chmod(0o770)
                try:
                    os.chown(directory, -1, CONTAINER_GID)
                except PermissionError:
                    if os.getgid() != CONTAINER_GID:
                        raise RuntimeErrorBase("Configure matching PROJECT_RUNTIME_CONTAINER_GID so the non-root container can access its isolated workspace.") from None
            try:
                os.chown(target, -1, CONTAINER_GID)
            except PermissionError:
                if os.getgid() != CONTAINER_GID:
                    raise RuntimeErrorBase("Configure matching PROJECT_RUNTIME_CONTAINER_GID so the non-root container can access its isolated workspace.") from None


def start_project(owner_id: str, workspace_id: str, files: dict[str, str], working_directory: str = "") -> dict[str, Any]:
    manifest = normalize_manifest(files)
    detection = detect_project(manifest, working_directory)
    run_id = f"{owner_id}:{workspace_id}"
    persisted = _read_entry(owner_id, workspace_id)
    if persisted and persisted.get("runtime_status") in {"queued", "preparing", "installing", "running"}:
        try:
            _restore_entry(persisted)
        except RuntimeErrorBase:
            pass
        if persisted.get("expires_at") and datetime.fromisoformat(persisted["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
            raise RuntimeErrorBase("A project runtime is already active for this workspace.")
    with _lock:
        prior = _runs.get(run_id)
        if prior and prior.get("status") in {"queued", "preparing", "installing", "running"}:
            raise RuntimeErrorBase("A project runtime is already active for this workspace.")
        _runs[run_id] = {"owner_id": owner_id, "workspace_id": workspace_id, "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(), "detection": detection, "container_id": None, "install_container_id": None, "directory": None, "preview_url": None, "preview_port": detection.get("preview_port"), "timeout_at": datetime.now(timezone.utc).timestamp() + TIMEOUT}
    root = Path(tempfile.mkdtemp(prefix="internsim-project-"))
    try:
        _runs[run_id]["directory"] = str(root)
        _persist_entry(_runs[run_id])
        _write_manifest(root, manifest)
        entry = _runs[run_id]
        timer = threading.Timer(TIMEOUT, _enforce_timeout, args=(run_id,))
        timer.daemon = True
        entry["timeout_timer"] = timer
        timer.start()
        threading.Thread(target=_prepare_and_run, args=(run_id, manifest, working_directory), daemon=True).start()
        return get_status(owner_id, workspace_id)
    except Exception as exc:
        shutil.rmtree(root, ignore_errors=True)
        with _lock:
            _runs[run_id].update({"status": "failed", "error": str(exc) if isinstance(exc, (RuntimeErrorBase, ValueError)) else "Could not prepare the isolated project container."})
            failure_entry = _runs[run_id]
        _persist_entry(failure_entry)
        if isinstance(exc, (RuntimeErrorBase, ValueError)):
            raise
        raise RuntimeErrorBase("Could not prepare the isolated project container.") from exc


def _container_limits() -> dict[str, Any]:
    return {
        "detach": True, "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
        "user": f"{CONTAINER_UID}:{CONTAINER_GID}", "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"], "pids_limit": PROCESS_LIMIT,
        "mem_limit": MEMORY_LIMIT, "nano_cpus": int(CPU_LIMIT * 1_000_000_000),
        "init": True,
    }


def _install_proxy_environment(mode: str, proxy_url: str) -> tuple[str | None, dict[str, str]]:
    """Return the proxy DNS alias and environment for a restricted installer network."""
    normalized_mode = mode.strip().casefold()
    if normalized_mode == "none":
        return None, {}
    if normalized_mode != "proxy":
        raise RuntimeErrorBase("PROJECT_RUNTIME_INSTALL_NETWORK must be 'none' or 'proxy'.")
    try:
        parsed = urlsplit(proxy_url)
        hostname = parsed.hostname or ""
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", hostname)
        ):
            raise ValueError("invalid proxy URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except (ValueError, TypeError):
        raise RuntimeErrorBase("Set PROJECT_RUNTIME_INSTALL_PROXY_URL to a credential-free HTTP(S) proxy URL on the installer network.") from None
    canonical_url = f"{parsed.scheme}://{hostname}:{port}"
    return hostname, {
        "HTTP_PROXY": canonical_url,
        "HTTPS_PROXY": canonical_url,
        "http_proxy": canonical_url,
        "https_proxy": canonical_url,
        "NO_PROXY": "localhost,127.0.0.1,::1",
        "no_proxy": "localhost,127.0.0.1,::1",
    }


def _create_install_network(client: Any, run_id: str, entry: dict[str, Any]) -> tuple[Any, Any, dict[str, str]]:
    """Create a per-install internal network connected only to the approved proxy."""
    proxy_alias, proxy_environment = _install_proxy_environment(INSTALL_NETWORK, INSTALL_PROXY_URL)
    if INSTALL_NETWORK == "none":
        return None, None, {}
    if not INSTALL_PROXY_CONTAINER:
        raise RuntimeErrorBase("Set PROJECT_RUNTIME_INSTALL_PROXY_CONTAINER to the operator-managed restricted-egress proxy container.")
    try:
        proxy = client.containers.get(INSTALL_PROXY_CONTAINER)
        proxy.reload()
        labels = getattr(proxy, "labels", {}) or {}
        attrs = getattr(proxy, "attrs", {}) or {}
        network_mode = attrs.get("HostConfig", {}).get("NetworkMode")
        docker_socket_mounted = any(
            mount.get("Destination") == "/var/run/docker.sock"
            for mount in attrs.get("Mounts", [])
        )
        privileged = attrs.get("HostConfig", {}).get("Privileged", False)
        if (
            proxy.status != "running"
            or labels.get("internsim.role") != "restricted-egress-proxy"
            or network_mode == "host"
            or docker_socket_mounted
            or privileged
        ):
            raise RuntimeErrorBase("The dependency proxy must be a running, labeled, non-privileged container without host networking or Docker socket access.")
    except RuntimeErrorBase:
        raise
    except Exception as exc:
        raise RuntimeErrorBase("Could not reach the configured dependency proxy container.") from exc
    suffix = hashlib.sha256(run_id.encode()).hexdigest()[:12] + "-" + secrets.token_hex(3)
    network = client.networks.create(
        name=f"internsim-install-{suffix}", driver="bridge", internal=True,
        check_duplicate=True,
        labels={"app": "internsim-install-network", "owner": entry["owner_id"], "workspace": entry["workspace_id"]},
    )
    try:
        network.connect(proxy, aliases=[proxy_alias])
    except Exception:
        try:
            network.remove()
        except Exception:
            pass
        raise RuntimeErrorBase("Could not connect the restricted dependency proxy to the isolated installer network.") from None
    return network, proxy, proxy_environment


def _remove_install_network(network: Any, proxy: Any = None) -> None:
    if not network:
        return
    if proxy:
        network.disconnect(proxy)
    network.remove()


def _bounded_install_logs(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = str(value or "").encode("utf-8", errors="replace")
    return raw[-INSTALL_LOG_LIMIT:].decode("utf-8", errors="replace")


def _capture_install_logs(entry: dict[str, Any], installer: Any) -> str:
    try:
        output = installer.logs(stdout=True, stderr=True, timestamps=True, tail=2000)
        with _lock:
            entry["installation_logs"] = _bounded_install_logs(output)
            return entry["installation_logs"]
    except Exception:
        # Preserve the most recent successful snapshot when Docker has removed the container.
        return entry.get("installation_logs", "")


def _resource_owned(resource: Any, app: str, owner_id: str, workspace_id: str) -> bool:
    labels = getattr(resource, "labels", None) or getattr(resource, "attrs", {}).get("Config", {}).get("Labels", {}) or {}
    if not labels:
        labels = getattr(resource, "attrs", {}).get("Labels", {}) or {}
    return labels.get("app") == app and labels.get("owner") == owner_id and labels.get("workspace") == workspace_id


def _remove_owned(resource: Any, app: str, entry: dict[str, Any]) -> bool:
    if resource and _resource_owned(resource, app, entry["owner_id"], entry["workspace_id"]):
        resource.remove(force=True) if app != "internsim-install-network" else resource.remove()
        return True
    return False


def _installer_exit_code(installer: Any) -> int:
    state = getattr(installer, "attrs", {}).get("State", {}) or {}
    code = state.get("ExitCode")
    if code is None:
        try:
            result = installer.wait(timeout=5)
        except Exception as exc:
            if "timeout" in type(exc).__name__.casefold() or "readtimeout" in type(exc).__name__.casefold():
                raise RuntimeErrorBase("Timed out reading the dependency installer exit status.") from exc
            raise RuntimeErrorBase("Could not read the dependency installer exit status from Docker.") from exc
        code = result.get("StatusCode", 1) if isinstance(result, dict) else 1
    return int(code)


def _installer_command(runtime_type: str) -> str:
    if runtime_type == "python":
        return (
            "run_phase() { phase=$1; shift; "
            "echo __INTERNSIM_INSTALL_PHASE__ phase=$phase state=start; "
            "started=$(date +%s%N); \"$@\"; result=$?; ended=$(date +%s%N); "
            "echo __INTERNSIM_INSTALL_PHASE__ phase=$phase state=complete elapsed_ms=$(((ended-started)/1000000)) exit_code=$result; "
            "return $result; }; "
            "run_phase venv python -m venv /workspace/.internsim-venv || exit $?; "
            "run_phase pip /workspace/.internsim-venv/bin/pip install -r requirements.txt || exit $?; "
            "echo __INTERNSIM_INSTALL_PHASE__ phase=installer state=complete"
        )
    return (
        "echo __INTERNSIM_INSTALL_PHASE__ phase=npm state=start; "
        "started=$(date +%s%N); npm install; result=$?; ended=$(date +%s%N); "
        "echo __INTERNSIM_INSTALL_PHASE__ phase=npm state=complete elapsed_ms=$(((ended-started)/1000000)) exit_code=$result; "
        "exit $result"
    )


def _recover_install_network_cleanup(client: Any, network_name: str, owner_id: str, workspace_id: str) -> None:
    network = client.networks.get(network_name)
    labels = getattr(network, "attrs", {}).get("Labels", {}) or {}
    if labels.get("app") != "internsim-install-network" or labels.get("owner") != owner_id or labels.get("workspace") != workspace_id:
        return
    endpoints = getattr(network, "attrs", {}).get("Containers", {}) or {}
    for container_id in endpoints:
        container = client.containers.get(container_id)
        container_labels = getattr(container, "labels", {}) or {}
        if container_labels.get("app") == "internsim-install" and container_labels.get("owner") == owner_id and container_labels.get("workspace") == workspace_id:
            container.remove(force=True)
        elif container_labels.get("internsim.role") == "restricted-egress-proxy":
            network.disconnect(container)
        else:
            raise RuntimeErrorBase("Unexpected container is attached to the persisted installer network; leaving it intact.")
    network.remove()


def _prepare_and_run(run_id: str, manifest: dict[str, str], working_directory: str) -> None:
    entry = _runs.get(run_id)
    if not entry:
        return
    client = None
    installer = None
    runtime_container = None
    network = None
    install_network = None
    install_proxy = None
    try:
        client = _docker_client()
        runtime_type = entry["detection"]["type"]
        image = PYTHON_IMAGE if runtime_type == "python" else NODE_IMAGE
        cwd = "/workspace" + ("/" + working_directory.strip("/") if working_directory.strip("/") else "")
        # The backend timer owns the execution deadline. A shell watchdog here could
        # kill pip before the worker records its final logs or failed state.
        install_command = _installer_command(runtime_type)
        install_network, install_proxy, install_environment = _create_install_network(client, run_id, entry)
        install_network_name = install_network.name if install_network else None
        entry.update({"install_network": install_network, "install_network_name": install_network_name, "install_proxy": install_proxy})
        _persist_entry(entry)
        install_args = _container_limits()
        install_args.update({
            "working_dir": cwd,
            "volumes": {entry["directory"]: {"bind": "/workspace", "mode": "rw"}},
            "network": install_network_name or "none",
            "environment": install_environment,
            "labels": {"app": "internsim-install", "owner": entry["owner_id"], "workspace": entry["workspace_id"]},
        })
        with _lock:
            entry["status"] = "installing"
        _persist_entry(entry)
        installer = client.containers.run(image, ["sh", "-lc", install_command], **install_args)
        with _lock:
            entry["install_container"] = installer
            entry["install_container_id"] = installer.id
        _persist_entry(entry)
        exit_code = None
        while True:
            with _lock:
                if entry.get("status") in {"stopped", "failed"}:
                    return
                remaining = entry.get("timeout_at", time.time() + TIMEOUT) - time.time()
            _capture_install_logs(entry, installer)
            try:
                installer.reload()
            except Exception as exc:
                raise RuntimeErrorBase("Dependency installer disappeared or became inaccessible before installation completed. Review the captured installation logs.") from exc
            if getattr(installer, "status", None) in {"exited", "dead"}:
                exit_code = _installer_exit_code(installer)
                _capture_install_logs(entry, installer)
                break
            if remaining <= 0:
                raise RuntimeErrorBase("Dependency installation exceeded the project runtime time limit. Review the captured installation logs.")
            time.sleep(min(INSTALL_STATUS_INTERVAL, max(0.05, remaining)))
        try:
            _remove_owned(installer, "internsim-install", entry)
        except Exception:
            pass
        installer = None
        entry.update({"install_container": None, "install_container_id": None})
        if install_network:
            _remove_install_network(install_network, install_proxy)
            install_network = None
            install_proxy = None
            entry.update({"install_network": None, "install_network_name": None, "install_proxy": None})
            _persist_entry(entry)
        if exit_code != 0:
            if INSTALL_NETWORK == "none":
                raise RuntimeErrorBase("Dependency installation failed. PROJECT_RUNTIME_INSTALL_NETWORK=none blocks package registry access; configure the approved restricted-egress proxy. Review installation logs.")
            raise RuntimeErrorBase("Dependency installation failed. Check proxy health and its approved package-registry allowlist. Review installation logs.")

        with _lock:
            entry["status"] = "preparing"
        _persist_entry(entry)
        network_name = "internsim-" + re.sub(r"[^a-zA-Z0-9_.-]", "-", run_id)[:35] + "-" + secrets.token_hex(4)
        network = client.networks.create(
            name=network_name, driver="bridge", internal=True, check_duplicate=True,
            labels={"app": "internsim", "owner": entry["owner_id"], "workspace": entry["workspace_id"]},
        )
        entry["network_name"] = network.name
        preview_port = entry["detection"].get("preview_port")
        runtime_command = None
        env = None
        if runtime_type == "python":
            if entry["detection"].get("framework") == "flask":
                module = PurePosixPath(entry["detection"]["entry"]).with_suffix("").as_posix().replace("/", ".")
                runtime_command = f"exec /workspace/.internsim-venv/bin/flask --app {shlex.quote(module)} run --host=0.0.0.0 --port=5000"
            else:
                runtime_command = f"exec /workspace/.internsim-venv/bin/python {shlex.quote(entry['detection']['entry'])}"
        else:
            script = entry["detection"].get("script")
            if script == "dev" and entry["detection"].get("framework") == "vite":
                runtime_command = "exec npm run dev -- --host 0.0.0.0 --port 3000"
            elif script == "dev" and entry["detection"].get("framework") == "next":
                runtime_command = "exec npm run dev -- --hostname 0.0.0.0 --port 3000"
            elif script == "start":
                runtime_command = "exec npm run start"
            else:
                runtime_command = f"exec node {shlex.quote(entry['detection']['entry'])}"
            env = {"HOST": "0.0.0.0", "PORT": "3000", "HOSTNAME": "0.0.0.0"}
        run_args = _container_limits()
        run_args.update({
            "working_dir": cwd,
            "volumes": {entry["directory"]: {"bind": "/workspace", "mode": "rw"}},
            "network": network.name,
            "environment": env or {},
            "labels": {"app": "internsim", "owner": entry["owner_id"], "workspace": entry["workspace_id"]},
        })
        if preview_port:
            run_args["ports"] = {f"{preview_port}/tcp": ("127.0.0.1", None)}
        runtime_container = client.containers.run(image, ["sh", "-lc", runtime_command], **run_args)
        runtime_container.reload()
        host_port = _published_port(runtime_container, preview_port) if preview_port else None
        with _lock:
            entry.update({"container": runtime_container, "container_id": runtime_container.id, "client": client, "network": network, "network_name": network.name, "host_port": host_port, "status": "running"})
        _persist_entry(entry)
    except Exception as exc:
        _capture_install_logs(entry, installer) if installer else None
        for resource in (installer, runtime_container):
            try:
                app = "internsim-install" if resource is installer else "internsim"
                _remove_owned(resource, app, entry)
            except Exception:
                pass
        try:
            if network and _resource_owned(network, "internsim", entry["owner_id"], entry["workspace_id"]):
                network.remove()
        except Exception:
            pass
        try:
            if install_network and _resource_owned(install_network, "internsim-install-network", entry["owner_id"], entry["workspace_id"]):
                _remove_install_network(install_network, install_proxy)
        except Exception:
            pass
        with _lock:
            if entry.get("status") in {"stopped", "failed"}:
                return
            entry.update({"status": "failed", "container": None, "container_id": None, "install_container": None, "install_container_id": None, "network": None, "network_name": None, "error": str(exc) if isinstance(exc, RuntimeErrorBase) else "Could not prepare or start the isolated project container."})
        entry.update({"install_network": None, "install_network_name": None, "install_proxy": None})
        if entry.get("directory"):
            shutil.rmtree(entry["directory"], ignore_errors=True)
            entry["directory"] = None
        timer = entry.get("timeout_timer")
        if timer:
            timer.cancel()
        _persist_entry(entry)


def _published_port(container: Any, port: int | None) -> int | None:
    if port not in {3000, 5000, 8000, 8080}:
        return None
    try:
        container.reload()
        mapping = container.attrs["NetworkSettings"]["Ports"].get(f"{port}/tcp") or []
        if len(mapping) != 1 or mapping[0].get("HostIp") not in {"127.0.0.1", "::1"}:
            return None
        return int(mapping[0]["HostPort"])
    except Exception:
        return None


def _owned(owner_id: str, workspace_id: str) -> dict[str, Any]:
    run_id = f"{owner_id}:{workspace_id}"
    entry = _runs.get(run_id)
    if not entry:
        persisted = _read_entry(owner_id, workspace_id)
        if persisted:
            entry = _restore_entry(persisted)
    if not entry:
        raise RuntimeErrorBase("No runtime exists for this workspace.")
    return entry


def _restore_entry(row: dict[str, Any]) -> dict[str, Any]:
    owner_id = str(row["owner_id"])
    workspace_id = str(row["workspace_id"])
    run_id = f"{owner_id}:{workspace_id}"
    status = row.get("runtime_status", "failed")
    expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    directory = row.get("workspace_dir")
    if directory:
        root = Path(tempfile.gettempdir()).resolve()
        candidate = Path(directory).resolve()
        if candidate.parent != root or not candidate.name.startswith("internsim-project-"):
            directory = None
    container = None
    network = None
    client = None
    install_network_cleanup_failed = False
    if status == "installing":
        if row.get("install_container_id"):
            try:
                client = _docker_client()
                installer = client.containers.get(row["install_container_id"])
                labels = getattr(installer, "labels", {}) or {}
                if labels.get("app") == "internsim-install" and labels.get("owner") == owner_id and labels.get("workspace") == workspace_id:
                    installer.remove(force=True)
            except Exception:
                pass
        if row.get("install_network_name"):
            try:
                client = client or _docker_client()
                _recover_install_network_cleanup(client, row["install_network_name"], owner_id, workspace_id)
            except Exception:
                install_network_cleanup_failed = True
        status = "failed"
        if install_network_cleanup_failed:
            row["error"] = "Interrupted dependency installation was stopped, but its temporary network still needs cleanup."
    if row.get("container_id") and status in {"queued", "preparing", "installing", "running"}:
        try:
            client = _docker_client()
            container = client.containers.get(row["container_id"])
            labels = getattr(container, "labels", {}) or {}
            if labels.get("app") != "internsim" or labels.get("owner") != owner_id or labels.get("workspace") != workspace_id:
                raise RuntimeErrorBase("Runtime container ownership does not match persisted metadata.")
            container.reload()
            if container.status == "exited":
                exit_code = container.attrs.get("State", {}).get("ExitCode", 1)
                container = None
                status = "failed" if exit_code else "stopped"
        except RuntimeErrorBase:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            container = None
            status = "failed"
            row["error"] = "Runtime ownership metadata did not match Docker."
        except Exception as exc:
            raise RuntimeErrorBase("Could not recover the project runtime from Docker.") from exc
    if expires_at <= datetime.now(timezone.utc) and container:
        try:
            _cache_logs({"installation_logs": "", "runtime_logs": ""}, container)
            container.kill()
            container.remove(force=True)
        except Exception:
            pass
        container = None
        status = "failed"
    if row.get("network_name") and status == "running":
        try:
            client = client or _docker_client()
            network = client.networks.get(row["network_name"])
            labels = getattr(network, "attrs", {}).get("Labels", {}) or {}
            if labels.get("app") != "internsim" or labels.get("owner") != owner_id or labels.get("workspace") != workspace_id:
                raise RuntimeErrorBase("Runtime network ownership does not match persisted metadata.")
        except RuntimeErrorBase:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            container = None
            status = "failed"
            row["error"] = "Runtime ownership metadata did not match Docker."
        except Exception as exc:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            status = "failed"
            container = None
            row["error"] = "Runtime network could not be recovered after the backend restarted."
    entry = {
        "owner_id": owner_id, "workspace_id": workspace_id, "container_id": row.get("container_id"),
        "container": container, "client": None, "directory": directory, "status": status,
        "install_container": None, "install_container_id": None, "install_network": None,
        "install_network_name": row.get("install_network_name") if install_network_cleanup_failed else None,
        "host_port": row.get("host_port"),
        "network_name": row.get("network_name"), "network": network,
        "created_at": row.get("created_at"), "timeout_at": expires_at.timestamp(),
        "detection": {"type": row.get("runtime_type"), "working_directory": ""},
        "preview_url": None, "preview_port": row.get("preview_port"), "error": row.get("error"),
        "exit_code": row.get("exit_code"),
    }
    with _lock:
        _runs[run_id] = entry
    if container:
        timer = threading.Timer(max(0, expires_at.timestamp() - datetime.now(timezone.utc).timestamp()), _enforce_timeout, args=(run_id,))
        timer.daemon = True
        entry["timeout_timer"] = timer
        timer.start()
    else:
        if entry.get("install_network_name"):
            try:
                client = client or _docker_client()
                _recover_install_network_cleanup(client, entry["install_network_name"], owner_id, workspace_id)
                entry["install_network_name"] = None
            except Exception:
                pass
        if row.get("network_name"):
            try:
                client = client or _docker_client()
                stale_network = client.networks.get(row["network_name"])
                labels = getattr(stale_network, "attrs", {}).get("Labels", {}) or {}
                if labels.get("app") == "internsim" and labels.get("owner") == owner_id and labels.get("workspace") == workspace_id:
                    stale_network.remove()
            except Exception:
                pass
        if directory:
            shutil.rmtree(directory, ignore_errors=True)
        entry.update({"status": status if status in {"failed", "stopped"} else "failed", "container_id": None, "directory": None, "network": None, "network_name": None})
        _persist_entry(entry)
    return entry


def _cache_logs(entry: dict[str, Any], container: Any) -> None:
    try:
        entry["runtime_logs"] = container.logs(stdout=True, stderr=True, timestamps=True, tail=2000).decode("utf-8", errors="replace")
    except Exception:
        entry["runtime_logs"] = ""


def _enforce_timeout(run_id: str) -> None:
    with _lock:
        entry = _runs.get(run_id)
        if not entry or entry.get("status") in {"stopped", "failed"}:
            return
        installer = entry.get("install_container")
        if installer:
            _capture_install_logs(entry, installer)
            _cleanup_failed_installer(entry, installer)
        container = entry.get("container")
        if container and _resource_owned(container, "internsim", entry["owner_id"], entry["workspace_id"]):
            try:
                _cache_logs(entry, container)
                container.kill()
                container.remove(force=True)
            except Exception:
                pass
        network = entry.get("network")
        if network and _resource_owned(network, "internsim", entry["owner_id"], entry["workspace_id"]):
            try:
                network.remove()
            except Exception:
                pass
        if entry.get("directory"):
            shutil.rmtree(entry["directory"], ignore_errors=True)
        entry.update({"status": "failed", "error": "Project runtime exceeded its execution time limit.", "directory": None, "container": None, "container_id": None, "install_container": None, "install_container_id": None, "install_network": None, "install_network_name": None, "install_proxy": None, "network": None, "network_name": None})
        _persist_entry(entry)


def get_status(owner_id: str, workspace_id: str) -> dict[str, Any]:
    with _lock:
        entry = _owned(owner_id, workspace_id)
        installer = entry.get("install_container")
        if entry.get("status") == "installing":
            initial_status = entry["status"]
            if not installer:
                entry.update({
                    "status": "failed",
                    "error": "Dependency installer reference is unavailable. Review the captured installation logs.",
                })
            else:
                try:
                    installer.reload()
                    if getattr(installer, "status", None) in {"exited", "dead"}:
                        _capture_install_logs(entry, installer)
                        exit_code = _installer_exit_code(installer)
                        entry["exit_code"] = exit_code
                        if exit_code:
                            entry["error"] = "Dependency installation failed. Review installation logs."
                            entry["status"] = "failed"
                        else:
                            # Let the existing preparation worker proceed to runtime
                            # startup; a completed installer is not an install failure.
                            entry["status"] = "preparing"
                            entry["install_container"] = None
                            entry["install_container_id"] = None
                    # A running installer remains in installing; polling never infers failure from elapsed time.
                except Exception:
                    _capture_install_logs(entry, installer)
                    entry.update({
                        "status": "failed",
                        "error": "Dependency installer disappeared or became inaccessible. Review the captured installation logs.",
                    })
            if entry["status"] != initial_status:
                if entry["status"] == "failed":
                    _cleanup_failed_installer(entry, installer)
                _persist_entry(entry)
        container = entry.get("container")
        if container:
            try:
                initial_status = entry["status"]
                container.reload()
                if container.status == "running" and entry["status"] in {"preparing", "installing"}:
                    output = container.logs(stdout=True, stderr=True, timestamps=False, tail=2000).decode("utf-8", errors="replace")
                    entry["status"] = "running" if "__INTERNSIM_INSTALL_COMPLETE__" in output else "installing"
                if container.status == "exited" and entry["status"] not in {"failed", "stopped"}:
                    entry["status"] = "failed" if container.attrs.get("State", {}).get("ExitCode", 0) else "stopped"
                    entry["exit_code"] = container.attrs.get("State", {}).get("ExitCode")
                    _cache_logs(entry, container)
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                    if entry.get("directory"):
                        shutil.rmtree(entry["directory"], ignore_errors=True)
                    timer = entry.get("timeout_timer")
                    if timer:
                        timer.cancel()
                    entry.update({"container": None, "directory": None, "container_id": None})
                if entry.get("timeout_at", 0) < datetime.now(timezone.utc).timestamp() and container.status == "running":
                    _enforce_timeout(f"{owner_id}:{workspace_id}")
                elif entry["status"] != initial_status:
                    _persist_entry(entry)
            except Exception:
                entry["status"] = "failed"
                entry["error"] = "Could not read container status."
                _persist_entry(entry)
        public_keys = {"workspace_id", "status", "created_at", "detection", "container_id", "preview_url", "error", "exit_code"}
        return {key: value for key, value in entry.items() if key in public_keys}


def get_logs(owner_id: str, workspace_id: str) -> dict[str, Any]:
    with _lock:
        entry = _owned(owner_id, workspace_id)
        container = entry.get("container")
        installer = entry.get("install_container")
        if installer:
            install_output = _capture_install_logs(entry, installer)
        else:
            install_output = entry.get("installation_logs", "")
        if not container:
            return {"installation_logs": install_output, "runtime_logs": entry.get("runtime_logs", entry.get("error", ""))}
        try:
            runtime_output = container.logs(stdout=True, stderr=True, timestamps=True, tail=2000).decode("utf-8", errors="replace")
        except Exception:
            runtime_output = "Unable to retrieve runtime logs."
        return {"installation_logs": install_output, "runtime_logs": runtime_output}


def _cleanup_failed_installer(entry: dict[str, Any], installer: Any = None) -> None:
    installer = installer or entry.get("install_container")
    if installer:
        try:
            _remove_owned(installer, "internsim-install", entry)
        except Exception:
            pass
    install_network = entry.get("install_network")
    if install_network and _resource_owned(install_network, "internsim-install-network", entry["owner_id"], entry["workspace_id"]):
        try:
            _remove_install_network(install_network, entry.get("install_proxy"))
        except Exception:
            pass
    entry.update({
        "install_container": None, "install_container_id": None,
        "install_network": None, "install_network_name": None, "install_proxy": None,
    })


def create_preview_session(owner_id: str, workspace_id: str, public_base_url: str) -> dict[str, str]:
    parsed_base = urlsplit(public_base_url)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace_id) or parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc or parsed_base.username or parsed_base.password or parsed_base.query or parsed_base.fragment:
        raise RuntimeErrorBase("Preview proxy public URL is invalid.")
    entry = _owned(owner_id, workspace_id)
    if entry.get("status") != "running" or not entry.get("preview_port") or not entry.get("host_port"):
        raise RuntimeErrorBase("This project has no running web preview available.")
    token = secrets.token_urlsafe(32)
    entry["preview_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
    entry["preview_token_used"] = True
    _persist_entry(entry)
    base = public_base_url.rstrip("/")
    return {"preview_url": f"{base}/api/github/student-project/runtime/preview/{workspace_id}/", "cookie_token": token}


def exchange_preview_token(workspace_id: str, token: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace_id) or len(token) > 128:
        raise RuntimeErrorBase("Preview session is invalid or expired.")
    row = _read_preview_entry(workspace_id, hashlib.sha256(token.encode()).hexdigest())
    if not row or row.get("preview_token_used") or row.get("runtime_status") != "running":
        raise RuntimeErrorBase("Preview session is invalid or expired.")
    expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    if expires <= datetime.now(timezone.utc):
        raise RuntimeErrorBase("Preview session has expired.")
    entry = _restore_entry(row) if f"{row['owner_id']}:{workspace_id}" not in _runs else _runs[f"{row['owner_id']}:{workspace_id}"]
    if entry.get("status") != "running" or not entry.get("host_port"):
        raise RuntimeErrorBase("Preview application is unavailable.")
    entry["preview_token_used"] = True
    _persist_entry(entry)
    return {"token": token, "owner_id": row["owner_id"]}


def preview_target(workspace_id: str, token: str) -> tuple[str, int]:
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", workspace_id):
        raise RuntimeErrorBase("Preview session is invalid or expired.")
    row = _read_preview_entry(workspace_id, hashlib.sha256(token.encode()).hexdigest())
    if not row or not row.get("preview_token_used") or row.get("runtime_status") != "running":
        raise RuntimeErrorBase("Preview session is invalid or expired.")
    if datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise RuntimeErrorBase("Preview session has expired.")
    entry = _runs.get(f"{row['owner_id']}:{workspace_id}") or _restore_entry(row)
    container = entry.get("container")
    if entry.get("status") != "running" or not container:
        raise RuntimeErrorBase("Preview application is stopped or unavailable.")
    actual_host_port = _published_port(container, entry.get("preview_port"))
    if not actual_host_port or actual_host_port != row.get("host_port"):
        raise RuntimeErrorBase("Preview application port is unavailable.")
    if PREVIEW_PROXY_HOST not in {"127.0.0.1", "::1", "host.docker.internal"}:
        raise RuntimeErrorBase("Preview proxy host is not an approved loopback gateway.")
    return PREVIEW_PROXY_HOST, actual_host_port


def stop_project(owner_id: str, workspace_id: str) -> dict[str, Any]:
    with _lock:
        entry = _owned(owner_id, workspace_id)
        container = entry.get("container")
        installer = entry.get("install_container")
        install_network = entry.get("install_network")
        try:
            if installer:
                installer.remove(force=True)
            if container:
                _cache_logs(entry, container)
                container.stop(timeout=3)
                container.remove(force=True)
            if install_network:
                _remove_install_network(install_network, entry.get("install_proxy"))
        except Exception:
            pass
        timer = entry.get("timeout_timer")
        if timer:
            timer.cancel()
        if entry.get("directory"):
            shutil.rmtree(entry["directory"], ignore_errors=True)
        if entry.get("network"):
            try:
                entry["network"].remove()
            except Exception:
                pass
        entry.update({"status": "stopped", "container": None, "container_id": None, "install_container": None, "install_container_id": None, "install_network": None, "install_network_name": None, "install_proxy": None, "network": None, "network_name": None, "directory": None})
        _persist_entry(entry)
        return get_status(owner_id, workspace_id)


def cleanup_all() -> None:
    with _lock:
        for entry in list(_runs.values()):
            try:
                container = entry.get("container")
                timer = entry.get("timeout_timer")
                if timer:
                    timer.cancel()
                if container:
                    container.remove(force=True)
                if entry.get("install_container"):
                    entry["install_container"].remove(force=True)
                if entry.get("install_network"):
                    _remove_install_network(entry["install_network"], entry.get("install_proxy"))
                if entry.get("network"):
                    entry["network"].remove()
                if entry.get("directory"):
                    shutil.rmtree(entry["directory"], ignore_errors=True)
                entry.update({"status": "stopped", "container": None, "container_id": None, "install_container": None, "install_container_id": None, "install_network": None, "install_network_name": None, "install_proxy": None, "network": None, "network_name": None, "directory": None})
                _persist_entry(entry)
            except Exception:
                pass
        _runs.clear()


atexit.register(cleanup_all)

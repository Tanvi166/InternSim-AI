import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from services import project_runtime_service as runtime

_mkdtemp = tempfile.mkdtemp


class ProjectDetectionTests(unittest.TestCase):
    def test_detects_python_requirements_and_entrypoint(self):
        result = runtime.detect_project({"requirements.txt": "flask", "app.py": "from flask import Flask"})
        self.assertEqual(result["type"], "python")
        self.assertEqual(result["entry"], "app.py")

    def test_detects_node_start_script(self):
        result = runtime.detect_project({
            "package.json": '{"scripts":{"start":"node src/server.js"}}',
            "src/server.js": "console.log('hi')",
        })
        self.assertEqual(result["type"], "node")
        self.assertEqual(result["script"], "start")

    def test_rejects_ambiguous_and_unsupported_projects(self):
        with self.assertRaisesRegex(ValueError, "ambiguous or unsupported"):
            runtime.detect_project({"requirements.txt": "flask", "main.py": "", "app.py": ""})
        with self.assertRaisesRegex(ValueError, "Unsupported project"):
            runtime.detect_project({"README.md": "hello"})

    def test_rejects_path_traversal_and_cwd_traversal(self):
        with self.assertRaises(ValueError):
            runtime.normalize_manifest({"../escape.py": "pass"})
        with self.assertRaises(ValueError):
            runtime.detect_project({"app.py": ""}, "../outside")

    def test_excludes_environment_and_private_key_files(self):
        result = runtime.normalize_manifest({"app.py": "", ".env": "secret", "config/.env.local": "secret", "id_rsa": "key"})
        self.assertEqual(result, {"app.py": ""})


class InstallerNetworkTests(unittest.TestCase):
    def test_installer_command_emits_secret_free_phase_timings(self):
        command = runtime._installer_command("python")
        self.assertIn("phase=$phase state=start", command)
        self.assertIn("run_phase venv", command)
        self.assertIn("run_phase pip", command)
        self.assertIn("elapsed_ms=", command)
        self.assertIn("phase=installer state=complete", command)
        self.assertNotIn("HTTP_PROXY", command)

    def test_none_mode_does_not_configure_a_proxy(self):
        alias, environment = runtime._install_proxy_environment("none", "")
        self.assertIsNone(alias)
        self.assertEqual(environment, {})

    def test_proxy_mode_requires_credential_free_http_proxy_url(self):
        alias, environment = runtime._install_proxy_environment("proxy", "http://registry-proxy:3128")
        self.assertEqual(alias, "registry-proxy")
        self.assertEqual(environment["HTTPS_PROXY"], "http://registry-proxy:3128")
        self.assertEqual(environment["https_proxy"], environment["HTTPS_PROXY"])
        with self.assertRaises(runtime.RuntimeErrorBase):
            runtime._install_proxy_environment("proxy", "http://user:password@registry-proxy:3128")
        with self.assertRaises(runtime.RuntimeErrorBase):
            runtime._install_proxy_environment("bridge", "")

    def test_creates_internal_isolated_network_and_connects_only_configured_proxy(self):
        class Proxy:
            status = "running"
            labels = {"internsim.role": "restricted-egress-proxy"}
            attrs = {"HostConfig": {"NetworkMode": "bridge", "Privileged": False}, "Mounts": []}
            def reload(self): pass
        class Containers:
            def get(self, name):
                self.name = name
                return Proxy()
        class Network:
            name = "internsim-install-test"
            def connect(self, container, aliases):
                self.connected_container, self.aliases = container, aliases
            def remove(self): pass
        class Networks:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return network
        network = Network()
        client = type("Client", (), {"containers": Containers(), "networks": Networks()})()
        entry = {"owner_id": "owner", "workspace_id": "repo"}
        with patch.object(runtime, "INSTALL_NETWORK", "proxy"), patch.object(runtime, "INSTALL_PROXY_CONTAINER", "approved-proxy"), patch.object(runtime, "INSTALL_PROXY_URL", "http://registry-proxy:3128"):
            created_network, proxy, environment = runtime._create_install_network(client, "owner:repo", entry)
        self.assertIs(created_network, network)
        self.assertIsInstance(proxy, Proxy)
        self.assertTrue(client.networks.kwargs["internal"])
        self.assertEqual(client.networks.kwargs["labels"]["app"], "internsim-install-network")
        self.assertEqual(network.aliases, ["registry-proxy"])
        self.assertEqual(environment["HTTPS_PROXY"], "http://registry-proxy:3128")

    def test_rejects_proxy_using_host_network_privilege_or_docker_socket(self):
        unsafe_configs = (
            {"HostConfig": {"NetworkMode": "host", "Privileged": False}, "Mounts": []},
            {"HostConfig": {"NetworkMode": "bridge", "Privileged": True}, "Mounts": []},
            {"HostConfig": {"NetworkMode": "bridge", "Privileged": False}, "Mounts": [{"Destination": "/var/run/docker.sock"}]},
        )
        for unsafe in unsafe_configs:
            with self.subTest(unsafe=unsafe):
                class Proxy:
                    status = "running"
                    labels = {"internsim.role": "restricted-egress-proxy"}
                    attrs = unsafe
                    def reload(self): pass
                class Client:
                    containers = type("Containers", (), {"get": lambda self, name: Proxy()})()
                    networks = type("Networks", (), {"create": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network must not be created"))})()
                with patch.object(runtime, "INSTALL_NETWORK", "proxy"), patch.object(runtime, "INSTALL_PROXY_CONTAINER", "bad-proxy"), patch.object(runtime, "INSTALL_PROXY_URL", "http://registry-proxy:3128"):
                    with self.assertRaisesRegex(runtime.RuntimeErrorBase, "non-privileged container without host networking"):
                        runtime._create_install_network(Client(), "owner:repo", {"owner_id": "owner", "workspace_id": "repo"})


class RuntimeLifecycleTests(unittest.TestCase):
    def tearDown(self):
        runtime.cleanup_all()

    def runtime_tempdir(self, prefix="runtime-test-", **kwargs):
        return _mkdtemp(prefix="runtime-test-", dir=Path(__file__).parent)

    def test_start_status_logs_stop_and_owner_isolation(self):
        class Container:
            status = "running"
            attrs = {"State": {"ExitCode": 0}, "NetworkSettings": {"Ports": {"5000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "41234"}]}}}
            def __init__(self, identifier, output, status="running", labels=None):
                self.id, self.output, self.status = identifier, output, status
                self.labels = labels or {"app": "internsim", "owner": "owner-1", "workspace": "repo-1"}
            def reload(self): pass
            def logs(self, **kwargs): return self.output
            def wait(self, **kwargs): return {"StatusCode": 0}
            def stop(self, **kwargs): self.status = "exited"
            def remove(self, **kwargs): pass
        class Network:
            name = "internsim-test"
            def remove(self): pass
        class Networks:
            def create(self, **kwargs): return Network()
        class Containers:
            count = 0
            def run(self, *args, **kwargs):
                self.count += 1
                labels = kwargs.get("labels", {})
                return Container(f"container-{self.count}", b"installer output" if self.count == 1 else b"runtime output", "exited" if self.count == 1 else "running", labels)
        class Client:
            def __init__(self): self.containers, self.networks = Containers(), Networks()
        client = Client()
        class ImmediateThread:
            def __init__(self, target, args, **kwargs): self.target, self.args = target, args
            def start(self): self.target(*self.args)
        class NoopTimer:
            daemon = False
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def cancel(self): pass

        with patch.object(runtime.tempfile, "mkdtemp", side_effect=self.runtime_tempdir), patch.object(runtime, "_docker_client", return_value=client), patch.object(runtime, "_read_entry", return_value=None), patch.object(runtime, "_persist_entry"), patch.object(runtime.threading, "Thread", ImmediateThread), patch.object(runtime.threading, "Timer", NoopTimer), patch.object(runtime, "INSTALL_NETWORK", "none"), patch.object(runtime, "INSTALL_PROXY_URL", ""):
            started = runtime.start_project("owner-1", "repo-1", {"requirements.txt": "flask", "app.py": ""})
            self.assertEqual(started["container_id"], "container-2")
            logs = runtime.get_logs("owner-1", "repo-1")
            self.assertIn("installer output", logs["installation_logs"])
            self.assertIn("runtime output", logs["runtime_logs"])
            with self.assertRaises(runtime.RuntimeErrorBase):
                runtime.get_status("owner-2", "repo-1")
            stopped = runtime.stop_project("owner-1", "repo-1")
            self.assertEqual(stopped["status"], "stopped")

    def test_docker_unavailable_is_reported_by_worker(self):
        entry = {"owner_id": "owner-1", "workspace_id": "repo-2", "status": "preparing", "detection": {"type": "python"}, "directory": None}
        runtime._runs["owner-1:repo-2"] = entry
        with patch.object(runtime, "_docker_client", side_effect=runtime.RuntimeErrorBase("Docker unavailable")), patch.object(runtime, "_persist_entry"):
            runtime._prepare_and_run("owner-1:repo-2", {}, "")
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["error"], "Docker unavailable")

    def test_missing_restricted_proxy_fails_before_installer_launch(self):
        class Containers:
            run_calls = 0
            def get(self, name): raise LookupError("proxy not found")
            def run(self, *args, **kwargs): self.run_calls += 1
        containers = Containers()
        class Client:
            def __init__(self): self.containers = containers
        client = Client()
        entry = {"owner_id": "owner", "workspace_id": "repo-3", "status": "preparing", "detection": {"type": "python"}, "directory": None}
        runtime._runs["owner:repo-3"] = entry
        with patch.object(runtime, "_docker_client", return_value=client), patch.object(runtime, "_persist_entry"), patch.object(runtime, "INSTALL_NETWORK", "proxy"), patch.object(runtime, "INSTALL_PROXY_CONTAINER", "missing-proxy"), patch.object(runtime, "INSTALL_PROXY_URL", "http://registry-proxy:3128"):
            runtime._prepare_and_run("owner:repo-3", {}, "")
        self.assertEqual(containers.run_calls, 0)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("Could not reach the configured dependency proxy", entry["error"])

    def test_registry_failure_in_none_mode_keeps_installer_logs_and_actionable_error(self):
        class Installer:
            id = "installer-1"
            status = "exited"
            labels = {"app": "internsim-install", "owner": "owner", "workspace": "repo-4"}
            attrs = {"State": {"ExitCode": 1}}
            def reload(self): pass
            def wait(self, **kwargs): return {"StatusCode": 1}
            def logs(self, **kwargs): return b"Temporary failure in name resolution while resolving pypi.org"
            def remove(self, **kwargs): pass
        class Containers:
            def __init__(self): self.run_calls = 0
            def run(self, *args, **kwargs):
                self.run_calls += 1
                self.kwargs = kwargs
                return Installer()
        containers = Containers()
        client = type("Client", (), {"containers": containers})()
        entry = {"owner_id": "owner", "workspace_id": "repo-4", "status": "preparing", "detection": {"type": "python"}, "directory": None}
        runtime._runs["owner:repo-4"] = entry
        with patch.object(runtime, "_docker_client", return_value=client), patch.object(runtime, "_persist_entry"), patch.object(runtime, "INSTALL_NETWORK", "none"), patch.object(runtime, "INSTALL_PROXY_URL", ""):
            runtime._prepare_and_run("owner:repo-4", {}, "")
        self.assertEqual(containers.run_calls, 1)
        self.assertEqual(containers.kwargs["network"], "none")
        self.assertNotIn("HTTPS_PROXY", containers.kwargs.get("environment", {}))
        self.assertEqual(entry["status"], "failed")
        self.assertIn("blocks package registry access", entry["error"])
        self.assertIn("Temporary failure in name resolution", entry["installation_logs"])

    def test_status_detects_nonzero_installer_and_persists_failure(self):
        class Installer:
            status = "exited"
            id = "installer-fail"
            labels = {"app": "internsim-install", "owner": "owner", "workspace": "exit"}
            attrs = {"State": {"ExitCode": 17}}
            removed = False
            def reload(self): pass
            def logs(self, **kwargs): return b"pip failed\n"
            def remove(self, **kwargs): self.removed = True
        installer = Installer()
        entry = {"owner_id": "owner", "workspace_id": "exit", "status": "installing", "install_container": installer,
                 "install_container_id": installer.id, "installation_logs": "", "timeout_at": 9999999999}
        runtime._runs["owner:exit"] = entry
        with patch.object(runtime, "_persist_entry") as persist:
            status = runtime.get_status("owner", "exit")
        self.assertEqual(status["status"], "failed")
        self.assertEqual(entry["exit_code"], 17)
        self.assertIsNone(entry["install_container"])
        self.assertIsNone(entry["install_container_id"])
        self.assertIn("pip failed", entry["installation_logs"])
        persist.assert_called_once_with(entry)

    def test_status_detects_disappeared_installer_and_logs_survive_cleanup(self):
        class StaleInstaller:
            id = "gone"
            labels = {"app": "internsim-install", "owner": "owner", "workspace": "gone"}
            def reload(self): raise LookupError("container missing")
            def logs(self, **kwargs): raise LookupError("container missing")
            def remove(self, **kwargs): pass
        entry = {"owner_id": "owner", "workspace_id": "gone", "status": "installing", "install_container": StaleInstaller(),
                 "install_container_id": "gone", "installation_logs": "last pip line", "timeout_at": 9999999999}
        runtime._runs["owner:gone"] = entry
        with patch.object(runtime, "_persist_entry") as persist:
            status = runtime.get_status("owner", "gone")
            logs = runtime.get_logs("owner", "gone")
        self.assertEqual(status["status"], "failed")
        self.assertIsNone(entry["install_container_id"])
        self.assertIn("last pip line", logs["installation_logs"])
        persist.assert_called_once_with(entry)

    def test_status_marks_missing_installer_reference_terminal(self):
        entry = {"owner_id": "owner", "workspace_id": "stale", "status": "installing", "install_container": None,
                 "install_container_id": "stale-id", "installation_logs": "cached", "timeout_at": 9999999999}
        runtime._runs["owner:stale"] = entry
        with patch.object(runtime, "_persist_entry"):
            status = runtime.get_status("owner", "stale")
        self.assertEqual(status["status"], "failed")
        self.assertIsNone(entry["install_container_id"])

    def test_healthy_installer_remains_installing(self):
        class Installer:
            status = "running"
            def reload(self): pass
        entry = {"owner_id": "owner", "workspace_id": "healthy", "status": "installing", "install_container": Installer(),
                 "timeout_at": 9999999999}
        runtime._runs["owner:healthy"] = entry
        with patch.object(runtime, "_persist_entry") as persist:
            status = runtime.get_status("owner", "healthy")
        self.assertEqual(status["status"], "installing")
        persist.assert_not_called()

    def test_successfully_exited_installer_moves_to_preparing(self):
        class Installer:
            status = "exited"
            attrs = {"State": {"ExitCode": 0}}
            def reload(self): pass
            def logs(self, **kwargs): return b"installed"
        entry = {"owner_id": "owner", "workspace_id": "complete", "status": "installing", "install_container": Installer(),
                 "install_container_id": "done", "timeout_at": 9999999999}
        runtime._runs["owner:complete"] = entry
        with patch.object(runtime, "_persist_entry"):
            status = runtime.get_status("owner", "complete")
        self.assertEqual(status["status"], "preparing")
        self.assertIsNone(entry["install_container_id"])

    def test_installer_logs_are_bounded_and_incrementally_cached(self):
        class Installer:
            def logs(self, **kwargs): return b"fresh output"
        entry = {"installation_logs": ""}
        self.assertEqual(runtime._capture_install_logs(entry, Installer()), "fresh output")
        with patch.object(runtime, "INSTALL_LOG_LIMIT", 8):
            self.assertEqual(runtime._bounded_install_logs("123456789"), "23456789")

    def test_status_persistence_failure_is_not_swallowed_after_installer_failure(self):
        class Installer:
            status = "exited"
            attrs = {"State": {"ExitCode": 1}}
            labels = {"app": "internsim-install", "owner": "owner", "workspace": "persist-fail"}
            def reload(self): pass
            def logs(self, **kwargs): return b"pip failed"
            def remove(self, **kwargs): pass
        entry = {"owner_id": "owner", "workspace_id": "persist-fail", "status": "installing", "install_container": Installer(),
                 "install_container_id": "id", "installation_logs": "", "timeout_at": 9999999999}
        runtime._runs["owner:persist-fail"] = entry
        with patch.object(runtime, "_persist_entry", side_effect=runtime.RuntimeErrorBase("metadata unavailable")):
            with self.assertRaisesRegex(runtime.RuntimeErrorBase, "metadata unavailable"):
                runtime.get_status("owner", "persist-fail")
        self.assertEqual(entry["status"], "failed")
        self.assertIsNone(entry["install_container_id"])
        self.assertIn("pip failed", entry["installation_logs"])

    def test_timeout_caches_installer_logs_and_persists_terminal_failure(self):
        class Installer:
            labels = {"app": "internsim-install", "owner": "owner", "workspace": "timeout"}
            def logs(self, **kwargs): return b"final pip progress"
            def remove(self, **kwargs): pass
        entry = {"owner_id": "owner", "workspace_id": "timeout", "status": "installing",
                 "install_container": Installer(), "install_container_id": "installer-timeout",
                 "installation_logs": "", "container": None, "container_id": None,
                 "install_network": None, "install_network_name": None, "install_proxy": None,
                 "network": None, "network_name": None, "directory": None}
        runtime._runs["owner:timeout"] = entry
        with patch.object(runtime, "_persist_entry") as persist:
            runtime._enforce_timeout("owner:timeout")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("execution time limit", entry["error"])
        self.assertIn("final pip progress", entry["installation_logs"])
        self.assertIsNone(entry["install_container_id"])
        persist.assert_called_once_with(entry)

    def test_failure_cleanup_does_not_remove_foreign_installer(self):
        class Foreign:
            labels = {"app": "internsim-install", "owner": "other", "workspace": "same"}
            removed = False
            def remove(self, **kwargs): self.removed = True
        foreign = Foreign()
        entry = {"owner_id": "owner", "workspace_id": "same", "install_container": foreign, "install_container_id": "foreign"}
        runtime._cleanup_failed_installer(entry)
        self.assertFalse(foreign.removed)
        self.assertIsNone(entry["install_container_id"])

if __name__ == "__main__":
    unittest.main()

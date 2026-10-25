# Project Runtime Manager

Project execution is separate from the existing Piston single-file endpoint. Install backend dependencies (including the Docker SDK), configure a Docker Engine reachable by the backend Docker SDK, apply `migrations/0007_project_runtime_sessions.sql` and `migrations/0008_project_runtime_install_network.sql`, and set `PROJECT_RUNTIME_*` values in the backend environment. The default images are Python 3.12 slim and Node 22 Alpine. The backend stores lifecycle metadata in Supabase; source files, logs, preview tokens, and credentials are not persisted there.

The runner accepts bounded workspace drafts (200 files / 10 MB by default). It supports Python projects with root-level `requirements.txt` and one of `app.py`, `main.py`, or `server.py`, and Node projects with `package.json` containing a `start` or `dev` script, or a `main`/`index.js` entry. A configurable repository-relative working directory is accepted by the API. Unsupported or ambiguous manifests return HTTP 422.

Each run receives an isolated installer container and then a separate application container. Both have CPU, memory, PID, and elapsed-time limits; containers drop Linux capabilities, set no-new-privileges, use a read-only root filesystem, run as a configured non-root UID/GID, and mount only that workspace. `.env*` files and common private-key/credential filenames are excluded. No Docker socket or backend credentials are mounted. The application gets a per-runtime Docker network marked `internal`; only its explicitly supported preview port can be published, bound to host loopback.

Dependency installation defaults to `PROJECT_RUNTIME_INSTALL_NETWORK=none`; the installer has no network and pip/npm registry DNS/downloads fail by design. Do not set this option to `bridge`, `host`, or an arbitrary Docker network. The repository includes an exact-host Squid ACL in `runtime-proxy/squid.conf`. It permits only HTTPS CONNECT to `pypi.org` and `files.pythonhosted.org`; add any additional required package host only after reviewing it. Squid ACL is the operator-managed egress policy. Do not rely on the Docker label or proxy URL as a substitute for testing that policy.

```dotenv
PROJECT_RUNTIME_INSTALL_NETWORK=proxy
PROJECT_RUNTIME_INSTALL_PROXY_CONTAINER=internsim-install-proxy
PROJECT_RUNTIME_INSTALL_PROXY_URL=http://internsim-install-proxy:3128
```

### Reproducible Windows / Docker Desktop proxy setup

Run these commands in PowerShell from `D:\Projects\PBL-sem5\backend`. Docker Desktop must be on Linux containers. The `ubuntu/squid` image is Canonical's published Squid image; review/pin an approved digest for a shared or production deployment. No proxy port is published to Windows. The proxy gets a dedicated egress network, while test/install clients use a separate internal network and can reach the internet only through the proxy.

```powershell
$ErrorActionPreference = 'Stop'
$proxyName = 'internsim-install-proxy'
$egressNetwork = 'internsim-proxy-egress'
$checkNetwork = 'internsim-proxy-check'
$configPath = (Resolve-Path '.\runtime-proxy\squid.conf').Path
$image = 'ubuntu/squid:6.13-25.04_beta'

docker network create --driver bridge $egressNetwork
docker pull $image
docker run -d --name $proxyName `
  --label internsim.role=restricted-egress-proxy `
  --network $egressNetwork --network-alias $proxyName `
  --restart unless-stopped --cpus 0.50 --memory 256m --pids-limit 128 `
  --cap-drop ALL --cap-add SETGID --cap-add SETUID `
  --security-opt no-new-privileges:true `
  --tmpfs /tmp:rw,noexec,nosuid,size=32m `
  --mount "type=bind,source=$configPath,target=/etc/squid/squid.conf,readonly" `
  $image

docker network create --driver bridge --internal $checkNetwork
docker network connect --alias $proxyName $checkNetwork $proxyName
```

Verify the policy before switching the backend to `proxy` mode. The first Python container is attached only to the `internal` check network. HTTPS to both exact PyPI hosts must succeed; HTTPS to an unapproved host and direct HTTPS without proxy must fail. This command exits nonzero if an expectation is not met:

```powershell
$probe = @'
import urllib.error, urllib.request
proxy = "http://internsim-install-proxy:3128"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
for url in ("https://pypi.org/simple/flask/", "https://files.pythonhosted.org/"):
    try:
        response = opener.open(url, timeout=20)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 407): raise SystemExit(f"SECURITY FAILURE: proxy denied approved host {url}") from exc
        print("ALLOWED", url, exc.code)
    else:
        print("ALLOWED", url, response.status)
        response.close()
for url in ("https://example.com/", "https://evil.pypi.org/"):
    try:
        opener.open(url, timeout=10)
    except urllib.error.URLError as exc:
        if "403 Forbidden" not in str(exc): raise SystemExit(f"SECURITY FAILURE: expected Squid ACL 403 for {url}, got {exc}") from exc
        print("BLOCKED by proxy ACL", url, "Squid 403 Forbidden")
    else:
        raise SystemExit(f"SECURITY FAILURE: proxy allowed {url}")
try:
    urllib.request.urlopen("https://example.com/", timeout=5)
except Exception as exc:
    print("BLOCKED direct from internal network", type(exc).__name__)
else:
    raise SystemExit("SECURITY FAILURE: internal client reached internet directly")
'@
$probe | docker run --rm -i --network $checkNetwork python:3.12-slim python -
if ($LASTEXITCODE -ne 0) { throw 'Proxy ACL/direct-egress verification failed; keep PROJECT_RUNTIME_INSTALL_NETWORK=none.' }
docker logs --tail 50 $proxyName
```

Also prove complete PyPI package resolution before enabling the backend. This disposable client is on the same `internal` network, so its only package egress is through Squid:

```powershell
docker run --rm --network $checkNetwork `
  -e HTTP_PROXY=http://internsim-install-proxy:3128 `
  -e HTTPS_PROXY=http://internsim-install-proxy:3128 `
  -e http_proxy=http://internsim-install-proxy:3128 `
  -e https_proxy=http://internsim-install-proxy:3128 `
  python:3.12-slim sh -lc 'python -m pip install --no-cache-dir --target /tmp/flask-install-test Flask && PYTHONPATH=/tmp/flask-install-test python -c "import flask; print(\"FLASK_INSTALL_OK\", flask.__version__)"'
```

The required success marker is `FLASK_INSTALL_OK` after pip reports `Successfully installed`. If any policy or package test fails, leave `PROJECT_RUNTIME_INSTALL_NETWORK=none`.

Only after the allow, deny, and real Flask pip checks pass, set these values in `backend/.env` (preserving other settings), ensure migration 0008 has been applied, and restart the backend from `backend/` with `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`:

```dotenv
PROJECT_RUNTIME_INSTALL_NETWORK=proxy
PROJECT_RUNTIME_INSTALL_PROXY_CONTAINER=internsim-install-proxy
PROJECT_RUNTIME_INSTALL_PROXY_URL=http://internsim-install-proxy:3128
```

The backend then creates a fresh Docker `bridge` network with `internal=true` for each installer, connects only that installer and the labeled proxy, and removes the network after installation. The installer gets proxy variables without proxy credentials and has no direct route. The project application container starts later on a different per-runtime internal network, gets no proxy variables, and cannot access the installer network. Do not use Docker host networking, privileged containers, published proxy ports, Docker socket mounts, or an unrestricted proxy.

The Squid policy uses exact `dstdomain` entries with no leading-dot domain suffixes, only permits CONNECT on port 443, and denies all other requests. Check the proxy access log for denied requests. If package downloads redirect to another host, installation should fail closed; review and add only the exact necessary host to the policy, then repeat both allowed and denied tests. This default policy is for Python/PyPI, not npm.

Apply `migrations/0008_project_runtime_install_network.sql` through the project's migration process after 0007; it stores the temporary installer network name for interrupted-install cleanup. Restart the backend after environment or migration changes. If the configured proxy container cannot be reached or is not labeled/running, installation stops before launching the installer.

To remove the local proxy after testing (from the same PowerShell session):

```powershell
docker network disconnect $checkNetwork $proxyName
docker network rm $checkNetwork
docker rm -f $proxyName
docker network rm $egressNetwork
docker image rm $image
```

If proxy validation or connection fails, installation stops before the installer starts and the runtime reports the setup error. If pip/npm still cannot resolve a registry, inspect the installer logs and proxy/firewall DNS and allowlist. The installer is removed after installation; install logs remain in backend memory for the active process only.

The preview proxy is authenticated: the normal authenticated preview API creates an HttpOnly, short-lived cookie, while the returned preview URL contains no credential. Configure `PROJECT_RUNTIME_PREVIEW_PUBLIC_BASE_URL` to the browser-reachable backend origin (HTTPS in production), and `PROJECT_RUNTIME_PREVIEW_PROXY_HOST` to the backend's loopback address for Docker-published ports. Proxy requests are scoped to the selected runtime and port, and request/response sizes are bounded. Supported preview frameworks are Flask, Vite, and Next.js dev scripts, plus Node start scripts. Other project types receive no preview port and are reported as unsupported for preview. A successful runtime status alone does not prove that a web app is serving HTTP.

Preview and end-to-end runtime execution require the metadata migrations, a working Docker daemon, an authenticated repository editor session, and the proxy configuration above if the project needs package downloads. From `backend/`, run `python -m unittest test_project_runtime.py`; then start a minimal Flask app through the authenticated UI, inspect both log panels, open the returned preview URL in the same browser session, verify the page loads, stop the runtime, and confirm its container/network are removed. Restart the backend during a second test to verify persisted metadata recovery. A passing unit suite or runtime status alone does not verify browser preview.

`Run Code` continues to use the existing Piston flow and is independent of this project runtime.

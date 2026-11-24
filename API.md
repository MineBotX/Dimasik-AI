# Dimasik API (OpenAI-compatible)

Dimasik exposes the locally installed Granite model through an authenticated HTTP API. The desktop app includes an API Generator that turns a task description into a task-specific system prompt and stores it locally. The API applies that prompt to every chat request.

## Requirements

- Python environment and dependencies from `requirements.txt`
- Dimasik's local Granite GGUF model and `llama-server.exe` installed through the desktop app

## Task-specific API Generator

In the Dimasik desktop app, open **API-генератор**, describe the API's purpose, and select Granite 4.2 3B. Dimasik uses the local Granite model to draft a system prompt defining the API role, input expectations, workflow, output format, and limitations. The generated prompt is saved in `brain/api_profile.json` and applied server-side to every request; client-supplied `system` messages remain ignored. The generator starts the authenticated API on `127.0.0.1:8787` and shows the newly created key once. The key is stored only as a hash. Keep the API bound to this computer unless you deliberately configure a protected remote deployment. DimaCore is not offered because it is an experimental compact model and is not suitable for arbitrary task-specific API behavior.

## Create a key

From the repository root:

```powershell
python -m assistant.api_server create-key --name "Crosshair Service" --rpm 30
```

The full `dm_live_...` token is displayed only once. Store it in the service's backend secret store / environment variables. Never put it in browser JavaScript, a desktop client, a public repository, or a URL.

To revoke a key, use the visible prefix (first 16 characters):

```powershell
python -m assistant.api_server revoke-key --prefix dm_live_xxxxx
```

Keys are stored as SHA-256 hashes in `brain/api_keys.sqlite3`; the raw key is not stored. Each key has its own requests-per-minute limit (default 30, configurable up to 600 when creating it).

## Start the API

```powershell
python -m assistant.api_server serve
```

Default address: `http://127.0.0.1:8787`. The server is loopback-only by default. The health endpoint is public; model and chat endpoints require a key.

```powershell
curl http://127.0.0.1:8787/health
```

## Chat request

```powershell
$headers = @{ Authorization = "Bearer $env:DIMASIK_API_KEY" }
$body = @{
  model = "dimasik"
  messages = @(@{ role = "user"; content = "Привет, Димасик!" })
  max_tokens = 512
} | ConvertTo-Json -Depth 8

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8787/v1/chat/completions" -Headers $headers -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

OpenAI-compatible routes:
- `GET /v1/models`
- `POST /v1/chat/completions`

The API accepts `user`, `assistant`, and `system` messages. Caller-provided system messages are ignored so a client cannot replace Dimasik's built-in instructions. Requests must use `Content-Type: application/json`, a fixed `Content-Length`, `model: "dimasik"`, and `stream: false`. Streaming, tools/function calling, image input, and exact token accounting are not implemented yet. `usage` fields are returned as zero placeholders. `max_tokens` must be a positive integer and is capped at 2048.

## Remote deployment and security

Do not expose this plain HTTP server directly to the public internet. For a remote service, run Dimasik on a trusted host and keep it bound to loopback. Put Caddy or nginx on the same host to terminate HTTPS and proxy requests to `127.0.0.1:8787`.

Example Caddy setup:
1. Point a DNS A/AAAA record for your domain to the server.
2. Install Caddy on that host and copy `deploy/Caddyfile.example` to its Caddy configuration, replacing `api.example.com` with your domain.
3. Allow inbound TCP 80 and 443 in the host firewall; do not expose port 8787 or the llama.cpp model port.
4. Start Dimasik with `python -m assistant.api_server serve --host 127.0.0.1 --port 8787` and reload Caddy. Caddy obtains and renews the TLS certificate automatically.

A non-loopback bind is intentionally disabled by default. Only consider `DIMASIK_ALLOW_REMOTE_BIND=1` for a separately secured network architecture; it is not needed for the reverse-proxy setup. Do not publish the llama.cpp server port. Restrict proxy access, use firewall rules, rotate/revoke keys if exposed, and back up the key database securely. The API currently uses in-memory per-key rate limiting; use a single API process or an external gateway for multi-worker deployments. Because the local Granite instance handles one generation at a time, the API admits only one inference at once and returns HTTP 503 (`model_busy`, `Retry-After: 5`) when it is occupied. Clients should retry with backoff rather than opening many simultaneous requests.

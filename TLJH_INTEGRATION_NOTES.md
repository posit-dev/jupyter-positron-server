# TLJH + Positron Server Integration Notes

## Problem Summary

When running positron-server behind jupyter-server-proxy on TLJH, there's a URL doubling issue during connection token validation redirects.

**Expected:** `http://localhost:8080/user/admin/positron/`
**Actual:** `http://localhost:8080/user/admin/positron/user/admin/positron`

## Current Working Flow (Workaround)

1. Click Positron launcher - get "Forbidden"
2. Manually add `?tkn=<TOKEN>` to URL - URL doubles but cookie (`vscode-tkn`) gets set
3. Close tab
4. Click Positron again - works (uses cookie, no redirect)

To find the token:
```bash
ps aux | grep positron-server | grep connection-token
```

## What We Tried (None Fixed the Redirect Issue)

### 1. Clear X-Forwarded-Prefix header
```python
"request_headers_override": {"X-Forwarded-Prefix": ""}
```
**Result:** Did not fix the redirect URL doubling

### 2. Set --server-base-path /
```python
command_arguments = [
    ...
    "--server-base-path",
    "/",
]
```
**Result:** Did not fix the redirect URL doubling

### 3. mappath function to strip proxy prefix
```python
def mappath(path):
    import re
    match = re.match(r"/user/[^/]+/positron(/.*)$", path)
    if match:
        return match.group(1)
    match = re.match(r"/user/[^/]+/positron$", path)
    if match:
        return "/"
    return path
```
**Result:** Did not fix the redirect URL doubling

### 4. rewrite_response to fix Location headers
```python
def rewrite_response(response, request):
    if "Location" in response.headers:
        location = response.headers["Location"]
        import re
        pattern = r"(/user/[^/]+/positron)/user/[^/]+/positron"
        fixed = re.sub(pattern, r"\1", location)
        if fixed != location:
            response.headers["Location"] = fixed
    return response
```
**Result:** Did not work (may not be supported by jupyter-server-proxy or wrong signature)

### 5. --without-connection-token
**Result:** Caused positron-server to crash with "Aborted"

## What Does Work

1. **Base URL without token:** `http://localhost:8080/user/admin/positron/` loads correctly (shows Forbidden, as expected)
2. **After cookie is set:** Subsequent requests work without URL doubling
3. **License validation:** Works correctly
4. **Positron itself:** Once authenticated, Positron Server runs fine

## Root Cause Analysis

The redirect happens after positron-server validates the connection token. Positron-server constructs a redirect URL to clear the token from the URL (for security). This redirect URL is incorrectly doubled.

Positron-server may be:
1. Reading the request path (`/user/admin/positron/`) and using it to construct redirects
2. Ignoring `--server-base-path /`
3. Using some internal mechanism to derive the base URL

## Files Modified

### jupyter-positron-server/__init__.py

Current working configuration:
```python
proxy_config_dict = {
    "new_browser_tab": True,
    "timeout": 120,
    "request_headers_override": {"X-Forwarded-Prefix": ""},
    "launcher_entry": {
        "enabled": True,
        "title": "Positron",
        "icon_path": os.path.join(_HERE, "icons/positron.svg"),
    },
}

command_arguments = [
    "--accept-server-license-terms",
    "--host", host,
    "--port", "{port}",
    "--connection-token", _CONNECTION_TOKEN,
    "--server-base-path", "/",
]
```

### Key functions:
- `which_positron_server()` - finds positron-server binary at `/opt/positron-server/bin/positron-server`
- `setup_positron_server()` - returns jupyter-server-proxy config

## Setup Instructions

### In TLJH container:

1. Install positron-server:
```bash
# Download and extract to /opt/positron-server/
```

2. Set environment variables in `/opt/tljh/config/jupyterhub_config.d/positron-env.py`:
```python
import os
path = os.environ.get("PATH", "/bin:/usr/bin")
c.SystemdSpawner.environment = {
    "PATH": f"/opt/positron-server/bin:/usr/local/bin:/opt/tljh/user/bin:{path}",
    "POSITRON_LICENSE_KEY_FILE": "/opt/license.lic",
}
```

3. Install jupyter-positron-server:
```bash
/opt/tljh/user/bin/pip install jupyter-positron-server
# Or from git:
/opt/tljh/user/bin/pip install git+https://github.com/posit-dev/jupyter-positron-server.git@update-mappath
```

4. Copy license file to `/opt/license.lic`

5. Restart: `systemctl restart jupyterhub`

## Testing Changes Locally

To test local changes without pushing to git:
```bash
# From Mac:
docker cp /Users/isabelizimm/code/jupyter-positron-server/jupyter-positron-server/__init__.py \
  $(docker ps -q):/opt/tljh/user/lib/python3.12/site-packages/jupyter_positron_server/__init__.py

# In container:
systemctl restart jupyterhub
```

## Next Steps to Investigate

1. **File issue on positron repo** about redirect behavior with `--server-base-path`

2. **Check jupyter-server-proxy version** and available options:
```bash
/opt/tljh/user/bin/pip show jupyter-server-proxy
```

3. **Look at jupyter-vscode-proxy** or similar projects to see how they handle token redirects

4. **Check if redirect is server-side (HTTP 302) or client-side (JavaScript)** - if JS, no server-side fix will work

5. **Try raw_socket_proxy mode** in jupyter-server-proxy (if available)

6. **Consider setting a fixed token** via `POSITRON_CONNECTION_TOKEN` env var for easier manual URL construction

## Additional Debugging (2026-04-09)

### What We Learned

#### 1. rewrite_response DOES fix the redirect
Adding a `rewrite_response` function that strips the proxy prefix from Location headers fixes the initial redirect:

```python
def rewrite_response(response, request):
    for header, v in response.headers.get_all():
        if header == "Location":
            u = urlparse(v)
            match = re.match(r"^/user/[^/]+/positron(/.*)?$", u.path)
            if match:
                fixed_path = match.group(1) if match.group(1) else "/"
                response.headers[header] = urlunparse(u._replace(path=fixed_path))
    return response
```

Log output shows it working:
```
302 GET /user/admin/positron/?tkn=... -> /user/admin/positron/
200 GET /user/admin/positron/
```

#### 2. Static resources still fail with 403
Even with the redirect fixed, static resources (JS, CSS, icons) fail with 403:
```
403 GET /user/admin/positron/user/admin/positron/releases-.../static/out/vs/code/browser/workbench/workbench.js
```

The paths are DOUBLED because positron-server embeds `/user/admin/positron/` in its generated HTML.

#### 3. mappath is NOT being called for these requests
Despite having mappath configured, no mappath log entries appear for the 403 requests. The 403 happens before mappath runs - possibly at an auth layer in jupyter-server-proxy.

#### 4. Token mismatch issue
The `path_info` in launcher_entry includes the token, but if the module is reloaded between generating the launcher URL and starting positron-server, the tokens won't match. This causes "Forbidden" errors even when using the launcher.

**Solution:** Either:
- Don't include token in launcher URL (accept manual token entry)
- Set `POSITRON_CONNECTION_TOKEN` environment variable for consistency
- Derive token deterministically from username

#### 5. absolute_url: True breaks initial request
Setting `absolute_url: True` makes positron-server receive the full path `/user/admin/positron/...`, but it returns 404 because it doesn't recognize that path.

#### 6. --server-base-path doesn't help
Tried:
- `--server-base-path /` - doesn't fix doubling
- `--server-base-path {base_url}positron/` - positron-server still generates doubled URLs

### Root Cause
positron-server generates internal URLs (for static resources) using the proxy prefix it receives via `X-Forwarded-Prefix` header. When the browser requests these URLs, they get doubled because:
1. Browser is already at `/user/admin/positron/`
2. HTML contains paths like `/user/admin/positron/releases-...` (should be relative or `/releases-...`)
3. Result: `/user/admin/positron/user/admin/positron/releases-...`

### What Partially Works
1. **rewrite_response** - Fixes redirect Location headers
2. **Launcher with token** - Works IF token matches (browser cache can cause mismatch)
3. **Cookie workaround** - After cookie is set (even via doubled URL), subsequent requests work

### What Doesn't Work
1. **mappath** - Not called for the doubled static resource requests (403 before mappath)
2. **absolute_url: True** - Breaks initial request (404)
3. **--server-base-path** - Doesn't prevent positron-server from generating doubled URLs
4. **Clearing X-Forwarded-Prefix** - Doesn't help

### Open Questions
1. Why isn't mappath called for the 403 requests? Is there an auth check happening first?
2. Can positron-server run without connection token? (`--without-connection-token` crashes)
3. How does the PyPI version of jupyter-positron-server work? (The working TLJH setup uses PyPI version)

## Issue Draft for Positron Repo

**Title:** Redirect URLs double the base path when using --server-base-path behind a reverse proxy

**Description:**
When running positron-server behind jupyter-server-proxy, redirects after connection token validation double the URL path prefix.

**Steps to reproduce:**
1. Run positron-server behind jupyter-server-proxy at `/user/<username>/positron/`
2. Navigate to `http://localhost:8080/user/admin/positron/?tkn=<valid-token>`
3. Positron validates token and issues redirect

**Expected:** Redirect to `http://localhost:8080/user/admin/positron/`
**Actual:** Redirect to `http://localhost:8080/user/admin/positron/user/admin/positron`

**Notes:**
- Clearing X-Forwarded-Prefix header does not resolve
- Setting --server-base-path / does not resolve
- After token stored in vscode-tkn cookie, subsequent requests work

**Additional finding:** Static resources also have doubled paths in the HTML, causing 403 errors for JS/CSS/icons. This is separate from the redirect issue - the HTML itself contains wrong paths.

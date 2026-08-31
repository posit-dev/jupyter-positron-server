"""Supervising launcher for positron-server.

jupyter-server-proxy runs this in place of positron-server:

    python -m jupyter_positron_server._launch <port> -- <positron-cmd...>

It starts positron-server, echoes its output onward so the Jupyter log is
unchanged, and keeps the last few lines. If positron-server exits before it
ever serves the port -- a rejected license, masked activation libraries, a
crash -- the launcher takes the port and serves those lines as a page. The
reason then lands in the tab the user opened, instead of only in a pod log the
user cannot read.

The page is served for a bounded window (``ERROR_PAGE_SECONDS``), then the
launcher exits nonzero so simpervisor restarts it and the launch is retried.
Held forever, the page would satisfy jupyter-server-proxy's one-shot readiness
check and the first failure would latch until the whole single-user server
restarts; the bounded window keeps "fix the environment and refresh" working.

Without this, jupyter-server-proxy restarts the failing process until its
readiness timeout expires and answers with "could not start positron in time",
which points at slowness no matter what actually went wrong.

On a healthy start the launcher is a transparent parent: it forwards
SIGTERM/SIGINT to positron-server and exits with its status.
"""

import collections
import html
import http.client
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_TAIL_LINES = 50
POLL_INTERVAL = 0.5  # seconds
DRAIN_GRACE = 2  # seconds to let the last output land before building the page
# How long the failure page stays up before the launcher exits and the launch
# is retried. Long enough to be read, short enough that a fixed environment
# comes back without waiting on anyone.
ERROR_PAGE_SECONDS = float(os.environ.get("POSITRON_LAUNCHER_ERROR_PAGE_SECONDS", 30))

DOCS_URL = "https://posit-dev.github.io/jupyter-positron-server/"
ACADEMIC_EMAIL = "academic-licenses@posit.co"

if sys.platform == "linux":
    import ctypes

    _libc = ctypes.CDLL(None, use_errno=True)
    _PR_SET_PDEATHSIG = 1

    def _die_with_launcher():
        # Runs in the forked child, pre-exec. jupyter-server-proxy's
        # ready-timeout kill SIGKILLs its direct child -- this launcher -- and
        # SIGKILL cannot be forwarded, so without this a hung positron-server
        # would outlive the launcher, still bound to the port.
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)

else:
    _die_with_launcher = None


def build_error_html(log_tail):
    """Return the page shown when positron-server fails to start.

    ``log_tail`` is positron-server's own output, escaped and shown verbatim:
    it names the cause far more reliably than anything this package could
    infer about a license it cannot validate.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Positron Server failed to start</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 40rem;
         margin: 4rem auto; padding: 0 1rem; line-height: 1.5; color: #1a1a1a; }}
  code {{ background: #f2f2f2; padding: 0.1rem 0.3rem; border-radius: 3px; }}
  a {{ color: #4c6ef5; }}
  pre {{ background: #f2f2f2; padding: 0.75rem; border-radius: 3px;
         white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
  <h1>Positron Server failed to start</h1>
  <p>Positron Server exited while starting up. The end of its log is below, and
  usually names the cause.</p>
  <p>A license that is missing, expired, or unreadable is the most common one.
  Set <code>POSITRON_LICENSE_KEY_FILE</code> to the path of your license file.
  Request a free academic license at
  <a href="mailto:{ACADEMIC_EMAIL}">{ACADEMIC_EMAIL}</a>, or see the
  <a href="{DOCS_URL}">documentation</a>.</p>
  <h2>Positron Server log</h2>
  <pre>{html.escape(log_tail)}</pre>
</body>
</html>
"""


class _ErrorPageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.server.error_html.encode("utf-8")
        # 503, not 200: jupyter-server-proxy's readiness check counts any
        # response, so the tab shows the page either way, but health checks
        # can still tell this apart from a healthy positron-server.
        self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        # Silence the default stderr request logging.
        pass


def make_server(port, error_html):
    """Bind ``127.0.0.1:<port>`` and answer every request with ``error_html``.

    ``ThreadingHTTPServer``: a half-open connection (a browser's speculative
    pre-connect, a TCP health probe) must not wedge the page for every later
    request. Its ``allow_reuse_address`` keeps taking over the port the
    just-exited child released from tripping over TIME_WAIT.
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), _ErrorPageHandler)
    server.error_html = error_html
    return server


def serve_error_page(port, log_tail):
    """Hold ``port`` with the failure page for ``ERROR_PAGE_SECONDS``.

    Returns False without serving when the port cannot be bound -- something
    else still holds it. The caller exits plainly in that case: a traceback
    here would make simpervisor restart the launcher in a tight, no-backoff
    loop against the same bind.
    """
    try:
        server = make_server(port, build_error_html(log_tail))
    except OSError:
        return False
    timer = threading.Timer(ERROR_PAGE_SECONDS, server.shutdown)
    timer.daemon = True
    timer.start()
    server.serve_forever()
    server.server_close()
    return True


def parse_args(argv):
    """Split ``argv`` (without the program name) into ``(port, child_cmd)``."""
    if len(argv) < 3 or argv[1] != "--":
        raise SystemExit(
            "usage: python -m jupyter_positron_server._launch <port> -- <cmd...>"
        )
    return int(argv[0]), list(argv[2:])


def _drain_output(pipe, ring):
    """Echo the child's output onward, keeping the last lines in ``ring``."""
    for raw in iter(pipe.readline, b""):
        line = raw.decode("utf-8", "replace")
        ring.append(line)
        sys.stderr.write(line)
        sys.stderr.flush()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Refuse to follow: urlopen then raises HTTPError, and the probe
        # counts that as a response -- the same rule jupyter-server-proxy
        # applies, probing with redirects disabled.
        return None


# A private opener for the probe: the default one honors http_proxy/HTTP_PROXY,
# and a corporate proxy answering for an unreachable 127.0.0.1 would look
# exactly like positron-server serving.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _watch_for_serving(port, served, stop):
    """Set ``served`` once the child answers HTTP on ``port``.

    An HTTP request, deliberately, not a TCP connect: positron-server binds the
    port before it validates the license, so "something is listening" is true
    for a moment even on a launch that never comes up. Only a response settles
    it. Any status counts, matching jupyter-server-proxy's own readiness check.
    """
    url = "http://127.0.0.1:{}/".format(port)
    while not stop.is_set():
        try:
            _opener.open(url, timeout=1).close()
            served.set()
            return
        except urllib.error.HTTPError:
            # An error status is still a response: it is up.
            served.set()
            return
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            # HTTPException covers a half-written response from a child still
            # initializing (BadStatusLine is not an OSError); an unhandled one
            # would kill this thread and every later exit would be
            # misclassified as a startup failure.
            time.sleep(POLL_INTERVAL)


def run(port, child_cmd):
    """Supervise ``child_cmd``; serve its log if it dies during startup."""
    ring = collections.deque(maxlen=LOG_TAIL_LINES)
    served = threading.Event()
    stop = threading.Event()
    signalled = threading.Event()

    try:
        child = subprocess.Popen(
            child_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=_die_with_launcher,
        )
    except OSError as exc:
        serve_error_page(port, f"Failed to launch: {exc}")
        return 1

    drain = threading.Thread(target=_drain_output, args=(child.stdout, ring), daemon=True)
    drain.start()
    threading.Thread(
        target=_watch_for_serving, args=(port, served, stop), daemon=True
    ).start()

    def _forward(signum, frame):
        signalled.set()
        stop.set()
        try:
            child.send_signal(signum)
        except ProcessLookupError:
            pass

    # signal.signal only works on the main thread; guard so run() stays callable
    # from a test thread.
    try:
        signal.signal(signal.SIGTERM, _forward)
        signal.signal(signal.SIGINT, _forward)
    except ValueError:
        pass

    returncode = child.wait()
    stop.set()

    if signalled.is_set() or served.is_set():
        # Culled by jupyter-server-proxy, or exited after it had served the
        # port. Either way there is nothing to explain; let the last of the
        # output land (the final stack trace tends to be in it), and leave the
        # exit alone so jupyter-server-proxy stays free to restart a server
        # that had worked.
        drain.join(timeout=DRAIN_GRACE)
        return returncode

    # It never served, so this is a startup failure. Hand signals back to the
    # default handlers before anything else: from here on a cull must terminate
    # the launcher, not be swallowed by _forward signalling an already-dead
    # child.
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except ValueError:
        pass
    drain.join(timeout=DRAIN_GRACE)
    if signalled.is_set():
        return returncode

    if serve_error_page(port, "".join(ring)):
        # Nonzero even if the child exited 0: simpervisor restarts only
        # nonzero exits, and that restart is what turns the bounded page
        # into a retry.
        return returncode or 1
    # The port is still held. Exit as the child did rather than fight for it;
    # jupyter-server-proxy's own timeout reports this one.
    return returncode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port, child_cmd = parse_args(argv)
    sys.exit(run(port, child_cmd))


if __name__ == "__main__":
    main()

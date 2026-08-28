"""Supervising launcher for positron-server.

jupyter-server-proxy runs this in place of positron-server:

    python -m jupyter_positron_server._launch <port> -- <positron-cmd...>

It starts positron-server, echoes its output onward so the Jupyter log is
unchanged, and keeps the last few lines. If positron-server exits before it
ever serves the port -- a rejected license, masked activation libraries, a
crash -- the launcher takes the port and serves those lines as a page. The
reason then lands in the tab the user opened, instead of only in a pod log the
user cannot read.

Without this, jupyter-server-proxy restarts the failing process until its
readiness timeout expires and answers with "could not start positron in time",
which points at slowness no matter what actually went wrong.

On a healthy start the launcher is a transparent parent: it forwards
SIGTERM/SIGINT to positron-server and exits with its status.
"""

import collections
import html
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG_TAIL_LINES = 50
POLL_INTERVAL = 0.5  # seconds
DRAIN_GRACE = 2  # seconds to let the last output land before building the page

DOCS_URL = "https://posit-dev.github.io/jupyter-positron-server/"
ACADEMIC_EMAIL = "academic-licenses@posit.co"


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
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        # Silence the default stderr request logging.
        pass


def make_server(port, error_html):
    """Bind ``127.0.0.1:<port>`` and answer every request with ``error_html``.

    ``HTTPServer`` sets ``allow_reuse_address``, so taking over the port the
    just-exited child released does not trip over TIME_WAIT.
    """
    server = HTTPServer(("127.0.0.1", port), _ErrorPageHandler)
    server.error_html = error_html
    return server


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
            urllib.request.urlopen(url, timeout=1).close()
            served.set()
            return
        except urllib.error.HTTPError:
            # An error status is still a response: it is up.
            served.set()
            return
        except (urllib.error.URLError, OSError):
            time.sleep(POLL_INTERVAL)


def run(port, child_cmd):
    """Supervise ``child_cmd``; serve its log if it dies during startup."""
    ring = collections.deque(maxlen=LOG_TAIL_LINES)
    served = threading.Event()
    stop = threading.Event()
    signalled = threading.Event()

    try:
        child = subprocess.Popen(
            child_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except OSError as exc:
        make_server(port, build_error_html(f"Failed to launch: {exc}")).serve_forever()
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
        # port. Either way there is nothing to explain, and leaving the exit
        # alone keeps jupyter-server-proxy free to restart a server that had
        # worked.
        return returncode

    # It never served, so this is a startup failure. Restore default signal
    # handling first, so a later cull still terminates us, then hold the port.
    drain.join(timeout=DRAIN_GRACE)
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except ValueError:
        pass
    make_server(port, build_error_html("".join(ring))).serve_forever()
    return returncode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port, child_cmd = parse_args(argv)
    sys.exit(run(port, child_cmd))


if __name__ == "__main__":
    main()

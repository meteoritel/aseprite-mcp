from . import mcp
from .core.lifecycle import install_client_watchdog
from .tools import *

if __name__ == "__main__":
    # A stdio server must not outlive the client that spawned it. The stdin
    # EOF this transport sees is not enough on its own (see core/lifecycle.py),
    # so the process also watches for a dead client itself.
    install_client_watchdog()
    mcp.run(transport='stdio')

import json
import os
from app.core import paths

# The OrbStack machine that runs the containers. Renaming it from the dashboard writes the
# new name to $HOMELAB_HOME/vm.json (read here at startup); the env var still wins if set.
VM_FILE = paths.state("vm")


def _saved_vm_name():
    try:
        with open(VM_FILE) as f:
            return json.load(f).get("vm_name") or None
    except (OSError, ValueError):
        return None


def _first_machine():
    """Before one is picked (setup screen / rename), use OrbStack's first machine, if any."""
    import shutil, subprocess
    if not shutil.which("orb"):
        return None
    try:
        out = subprocess.run(["orb", "list", "-q"], capture_output=True, text=True, timeout=5).stdout
        return (out.split() or [None])[0]
    except Exception:
        return None


VM_NAME = os.environ.get("HOMELAB_VM_NAME") or _saved_vm_name() or _first_machine() or "default"
VM_CMD_PREFIX = ["orb", "-m", VM_NAME]

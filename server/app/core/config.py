import json
import os

# The OrbStack machine that runs the containers. Renaming it from the dashboard writes the
# new name to ~/.homelab_vm.json (read here at startup); the env var still wins if set.
VM_FILE = os.path.expanduser("~/.homelab_vm.json")


def _saved_vm_name():
    try:
        with open(VM_FILE) as f:
            return json.load(f).get("vm_name") or None
    except (OSError, ValueError):
        return None


VM_NAME = os.environ.get("HOMELAB_VM_NAME") or _saved_vm_name() or "casaos"
VM_CMD_PREFIX = ["orb", "-m", VM_NAME]

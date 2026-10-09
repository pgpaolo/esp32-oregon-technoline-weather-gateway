Import("env")

from pathlib import Path

# PlatformIO executes pre: scripts through SCons, where __file__ is not
# guaranteed to exist. Keep the large idempotent integration pass standalone
# and execute it with an explicit script path so its existing ROOT logic works
# both under PlatformIO and when inspected/run as normal Python.
script = Path(env.subst("$PROJECT_DIR")) / "scripts" / "apply_remote_access_ota.py"
scope = {"__file__": str(script), "__name__": "__main__"}
exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), scope, scope)

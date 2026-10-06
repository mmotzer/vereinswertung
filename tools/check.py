"""Run the same repository checks locally and in CI."""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATHS = [
    "app.py",
    "club_platform.py",
    "manage.py",
    "platform_manage.py",
    "package.py",
    "vereinswertung",
    "tests",
    "tools",
]


def run(*args, cwd=ROOT, env=None):
    """Stop immediately when a check fails."""
    print("Checking: " + " ".join(str(arg) for arg in args), flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main():
    if not shutil.which("node"):
        raise SystemExit("Node.js 22 is required for JavaScript syntax checks.")
    run(sys.executable, "-m", "ruff", "check", *PYTHON_PATHS)
    run(sys.executable, "-m", "ruff", "format", "--check", *PYTHON_PATHS)
    for script in sorted((ROOT / "static").glob("*.js")):
        run("node", "--check", str(script))
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests")
    run(sys.executable, "package.py")
    with tempfile.TemporaryDirectory(prefix="vereinswertung-source-") as folder:
        with zipfile.ZipFile(
            ROOT / "artifacts/vereinswertung-nas.zip"
        ) as archive:
            for name in archive.namelist():
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise SystemExit("Unsafe archive path: " + name)
                if path.suffix in {".sqlite", ".env"} or name.startswith(
                    ("data/", ".runtime/", ".venv/")
                ):
                    raise SystemExit("Private runtime file in archive: " + name)
            archive.extractall(folder)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        run(
            sys.executable,
            "-c",
            "import app, club_platform; from vereinswertung import rating, storage",
            cwd=folder,
            env=env,
        )
    print("All repository checks passed.")


if __name__ == "__main__":
    main()

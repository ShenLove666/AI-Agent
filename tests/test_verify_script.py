from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify.ps1"


def test_verify_script_preserves_native_stage_exit_code(tmp_path: Path) -> None:
    powershell = shutil.which("powershell")
    assert powershell is not None, "Windows PowerShell is required for verify.ps1"

    python_stub = tmp_path / "python-stub.cmd"
    python_stub.write_text("@exit /b 42\r\n", encoding="ascii")

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(VERIFY_SCRIPT),
            "-PythonExecutable",
            str(python_stub),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 42, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

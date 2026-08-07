from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from app.main import create_app
from scripts.check_api_contracts import (
    ACTIVE_SERVICE_PATHS,
    ApiCall,
    compare_with_openapi,
    extract_service_calls,
    main,
    normalize_path,
)
from fastapi import FastAPI


def test_active_frontend_service_calls_exist_in_openapi():
    """A changed active frontend path must fail until FastAPI exposes it."""
    calls = extract_service_calls(ACTIVE_SERVICE_PATHS)
    calls.add(ApiCall("POST", "/rag/v3/chat"))

    missing = compare_with_openapi(calls, create_app().openapi())

    assert missing == set()


def test_template_parameters_are_normalized():
    """Changing a template parameter name must not create a false mismatch."""
    assert normalize_path("/conversations/${conversationId}/messages") == "/conversations/{}/messages"


def test_extraction_handles_type_arguments_and_api_prefix(tmp_path: Path):
    """Removing literal extraction would leave frontend calls outside the comparison."""
    service = tmp_path / "sampleService.ts"
    service.write_text(
        '''
        api.get<Array<Record<string, unknown>>>("/api/v1/users");
        api.patch(`/api/v1/conversations/${conversationId}`, payload);
        api.post(url, payload);
        ''',
        encoding="utf-8",
    )

    calls = extract_service_calls([service])

    assert calls == {
        ApiCall("GET", "/users"),
        ApiCall("PATCH", "/conversations/{}"),
    }


def test_checker_cli_validates_the_real_fastapi_application():
    """Running the file directly must use the real application, not fail to import it."""
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/check_api_contracts.py"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Active frontend API calls:" in result.stdout


def test_checker_reports_unmatched_method_and_path(tmp_path: Path, capsys):
    """Dropping an OpenAPI route must make the checker fail with its method and path."""
    service = tmp_path / "unmatchedService.ts"
    service.write_text('api.get("/unmatched");', encoding="utf-8")

    exit_code = main([service], FastAPI())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "GET /unmatched" in captured.err

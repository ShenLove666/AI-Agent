from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from app.main import create_app
from scripts.check_api_contracts import (
    ACTIVE_SERVICE_PATHS,
    ApiCall,
    ContractExtractionError,
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


def test_real_multiline_generic_call_is_extracted_from_active_session_service():
    """A semicolon inside a multiline generic must not hide GET /conversations."""
    calls = extract_service_calls(ACTIVE_SERVICE_PATHS)

    assert ApiCall("GET", "/conversations") in calls
    # Includes the active retail and support workbench services as well as the
    # original chat/session surface. Keep this count intentional so newly
    # activated clients cannot silently bypass the OpenAPI gate.
    assert len(calls) == 73

    calls.add(ApiCall("POST", "/rag/v3/chat"))
    assert len(calls) == 74


def test_template_parameters_are_normalized():
    """Changing a template parameter name must not create a false mismatch."""
    assert normalize_path("/conversations/${conversationId}/messages") == "/conversations/{}/messages"
    assert normalize_path("users") == "/users"
    assert normalize_path("api/v1/users") == "/users"


def test_extraction_handles_type_arguments_and_api_prefix(tmp_path: Path):
    """Removing literal extraction would leave frontend calls outside the comparison."""
    service = tmp_path / "sampleService.ts"
    service.write_text(
        '''
        api.get<Array<Record<string, unknown>>>("/api/v1/users");
        api.patch(`/api/v1/conversations/${conversationId}`, payload);
        ''',
        encoding="utf-8",
    )

    calls = extract_service_calls([service])

    assert calls == {
        ApiCall("GET", "/users"),
        ApiCall("PATCH", "/conversations/{}"),
    }


def test_dynamic_first_argument_fails_with_filename_line_and_method(tmp_path: Path):
    """A dynamic active endpoint cannot be verified and must never be silently skipped."""
    service = tmp_path / "dynamicService.ts"
    service.write_text('api.post(url, payload);', encoding="utf-8")

    try:
        extract_service_calls([service])
    except ContractExtractionError as error:
        message = str(error)
    else:
        raise AssertionError("dynamic active call was silently ignored")

    assert "dynamicService.ts:1" in message
    assert "POST" in message
    assert "first argument must be a string or template literal" in message


def test_comments_between_method_and_parenthesis_do_not_hide_dynamic_call(tmp_path: Path):
    """A comment after an axios method must not bypass the dynamic-call guard."""
    service = tmp_path / "commentSeparatedDynamicService.ts"
    service.write_text('api.post /* request URL resolved elsewhere */ (url, payload);', encoding="utf-8")

    try:
        extract_service_calls([service])
    except ContractExtractionError as error:
        message = str(error)
    else:
        raise AssertionError("comment-separated dynamic call was silently ignored")

    assert "commentSeparatedDynamicService.ts:1" in message
    assert "POST" in message


def test_api_like_text_in_comments_and_plain_strings_is_ignored(tmp_path: Path):
    """Non-code text must not be mistaken for an active frontend call."""
    service = tmp_path / "nonCodeApiTextService.ts"
    service.write_text(
        '''
        // api.post(url)
        /* api.get(endpoint) */
        const single = 'api.delete(target)';
        const double = "api.patch(target)";
        const template = `api.put(target)`;
        ''',
        encoding="utf-8",
    )

    assert extract_service_calls([service]) == set()


def test_template_interpolation_is_scanned_as_code(tmp_path: Path):
    """A dynamic axios call inside ${...} must not be hidden by a template literal."""
    service = tmp_path / "templateInterpolationService.ts"
    service.write_text('const label = `${api.post(url, payload)}`;', encoding="utf-8")

    try:
        extract_service_calls([service])
    except ContractExtractionError as error:
        message = str(error)
    else:
        raise AssertionError("template interpolation dynamic call was silently ignored")

    assert "templateInterpolationService.ts:1" in message
    assert "POST" in message


def test_regex_brace_inside_template_interpolation_does_not_hide_dynamic_call(tmp_path: Path):
    """A regex brace must not close ${...} before a later axios call is scanned."""
    service = tmp_path / "templateInterpolationRegexService.ts"
    service.write_text(
        'const label = `${ /}/.test(x) && api.post(url, payload) }`;',
        encoding="utf-8",
    )

    try:
        extract_service_calls([service])
    except ContractExtractionError as error:
        message = str(error)
    else:
        raise AssertionError("regex brace hid a dynamic call inside template interpolation")

    assert "templateInterpolationRegexService.ts:1" in message
    assert "POST" in message


def test_regex_literals_are_ignored_and_division_keeps_following_call_visible(tmp_path: Path):
    """Regex text is non-code, while a division slash cannot swallow later axios calls."""
    service = tmp_path / "regexAndDivisionService.ts"
    service.write_text(
        r'''
        const simple = /api.post(url)/;
        const escaped = /api\.delete\(target\)[/]/gi;
        const ratio = total / divisor;
        api.get("/after-division");
        ''',
        encoding="utf-8",
    )

    assert extract_service_calls([service]) == {ApiCall("GET", "/after-division")}


def test_numeric_literal_makes_following_slash_division(tmp_path: Path):
    """A numeric left operand must not let division swallow a dynamic axios call."""
    service = tmp_path / "numericDivisionService.ts"
    service.write_text(
        "const ratio = 10 / api.post(url, payload);",
        encoding="utf-8",
    )

    try:
        extract_service_calls([service])
    except ContractExtractionError as error:
        message = str(error)
    else:
        raise AssertionError("division after a numeric literal hid a dynamic call")

    assert "numericDivisionService.ts:1" in message
    assert "POST" in message


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

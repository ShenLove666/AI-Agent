from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from fastapi import FastAPI


HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
API_PREFIX = "/api/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SERVICE_DIRECTORY = PROJECT_ROOT / "web" / "src" / "services"
ACTIVE_SERVICE_PATHS = tuple(
    SERVICE_DIRECTORY / filename
    for filename in (
        "api.ts",
        "authService.ts",
        "chatService.ts",
        "dashboardService.ts",
        "knowledgeService.ts",
        "ragTraceService.ts",
        "sessionService.ts",
        "settingsService.ts",
        "userService.ts",
    )
)

API_METHOD_RE = re.compile(r"\bapi\.(?P<method>get|post|put|patch|delete)\b")
TEMPLATE_PARAMETER_RE = re.compile(r"\$\{[^}]+\}")
OPENAPI_PARAMETER_RE = re.compile(r"\{[^}]+\}")


@dataclass(frozen=True, order=True)
class ApiCall:
    method: str
    path: str


class ContractExtractionError(ValueError):
    """Raised when an active frontend API call cannot be verified statically."""


def normalize_path(path: str) -> str:
    """Normalize frontend and OpenAPI paths into a common comparison form."""
    normalized = path.split("?", 1)[0].split("#", 1)[0]
    normalized = TEMPLATE_PARAMETER_RE.sub("{}", normalized)
    normalized = OPENAPI_PARAMETER_RE.sub("{}", normalized)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized == API_PREFIX:
        return "/"
    if normalized.startswith(f"{API_PREFIX}/"):
        return normalized[len(API_PREFIX) :]
    return normalized


def _skip_comment(source: str, index: int) -> int | None:
    if source.startswith("//", index):
        newline = source.find("\n", index + 2)
        return len(source) if newline == -1 else newline + 1
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return len(source) if end == -1 else end + 2
    return None


def _skip_trivia(source: str, index: int) -> int:
    """Skip whitespace and TypeScript comments between call tokens."""
    while index < len(source):
        if source[index].isspace():
            index += 1
            continue
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        break
    return index


def _skip_plain_literal(source: str, index: int) -> int:
    """Skip a non-code quoted literal while searching for axios method tokens."""
    quote = source[index]
    index += 1
    escaped = False
    while index < len(source):
        character = source[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return index + 1
        index += 1
    return len(source)


def _iter_code_api_methods(source: str):
    """Yield API method matches found only in TypeScript code, never text/comments."""
    index = 0
    while index < len(source):
        comment_end = _skip_comment(source, index)
        if comment_end is not None:
            index = comment_end
            continue
        if source[index] in {"'", '"', "`"}:
            index = _skip_plain_literal(source, index)
            continue
        match = API_METHOD_RE.match(source, index)
        if match is not None:
            yield match
            index = match.end()
            continue
        index += 1


def _skip_balanced_type_arguments(source: str, index: int, path: Path) -> int:
    """Skip nested TypeScript ``<...>`` while preserving quoted string contents."""
    depth = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        character = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character in {"'", '"', "`"}:
            quote = character
        elif (comment_end := _skip_comment(source, index)) is not None:
            index = comment_end
            continue
        elif character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    line = source.count("\n", 0, index) + 1
    raise ContractExtractionError(f"{path}:{line}: unclosed TypeScript type arguments")


def _read_literal_argument(source: str, index: int, path: Path, method: str) -> tuple[str, int]:
    """Read the literal first argument after a verified axios method call."""
    line = source.count("\n", 0, index) + 1
    if index >= len(source) or source[index] not in {"'", '"', "`"}:
        raise ContractExtractionError(
            f"{path}:{line}: {method}: first argument must be a string or template literal"
        )

    quote = source[index]
    start = index + 1
    index = start
    escaped = False
    while index < len(source):
        character = source[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return source[start:index], index + 1
        index += 1
    raise ContractExtractionError(f"{path}:{line}: {method}: unclosed string or template literal")


def _extract_source_calls(source: str, path: Path) -> set[ApiCall]:
    calls: set[ApiCall] = set()
    for match in _iter_code_api_methods(source):
        method = match.group("method").upper()
        index = _skip_trivia(source, match.end())
        if index < len(source) and source[index] == "<":
            index = _skip_balanced_type_arguments(source, index, path)
            index = _skip_trivia(source, index)
        if index >= len(source) or source[index] != "(":
            continue
        literal_path, _ = _read_literal_argument(
            source, _skip_trivia(source, index + 1), path, method
        )
        calls.add(ApiCall(method, normalize_path(literal_path)))
    return calls


def extract_service_calls(paths: Sequence[Path]) -> set[ApiCall]:
    """Extract literal axios calls from the deliberately scoped active services."""
    calls: set[ApiCall] = set()
    for path in paths:
        calls.update(_extract_source_calls(path.read_text(encoding="utf-8"), path))
    return calls


def openapi_calls(app: FastAPI) -> set[ApiCall]:
    """Return all HTTP method/path pairs exposed by this app's generated OpenAPI."""
    schema = app.openapi()
    calls: set[ApiCall] = set()
    for path, operations in schema.get("paths", {}).items():
        for method in operations:
            normalized_method = method.upper()
            if normalized_method in HTTP_METHODS:
                calls.add(ApiCall(normalized_method, normalize_path(path)))
    return calls


def compare_with_openapi(
    frontend_calls: set[ApiCall], openapi_schema: Mapping[str, object]
) -> set[ApiCall]:
    """Return active frontend calls which FastAPI does not document."""
    documented: set[ApiCall] = set()
    paths = openapi_schema.get("paths", {})
    if not isinstance(paths, Mapping):
        return set(frontend_calls)
    for path, operations in paths.items():
        if not isinstance(path, str) or not isinstance(operations, Mapping):
            continue
        for method in operations:
            if isinstance(method, str) and method.upper() in HTTP_METHODS:
                documented.add(ApiCall(method.upper(), normalize_path(path)))
    return frontend_calls - documented


def calls_hash(calls: set[ApiCall]) -> str:
    """Create a stable fingerprint for the active frontend API baseline."""
    payload = "\n".join(f"{call.method} {call.path}" for call in sorted(calls))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main(
    paths: Sequence[Path] = ACTIVE_SERVICE_PATHS,
    app: FastAPI | None = None,
) -> int:
    """Check the selected frontend services against a real FastAPI application."""
    from app.main import create_app

    calls = extract_service_calls(paths)
    # chatStore.ts sends this SSE request through fetch, not the axios instance.
    calls.add(ApiCall("POST", "/rag/v3/chat"))
    missing = compare_with_openapi(calls, (app if app is not None else create_app()).openapi())

    print(f"Active frontend API calls: {len(calls)}")
    print(f"Active frontend API call hash: {calls_hash(calls)}")
    if missing:
        print("OpenAPI is missing active frontend calls:", file=sys.stderr)
        for call in sorted(missing):
            print(f"{call.method} {call.path}", file=sys.stderr)
        return 1

    print("All active frontend calls are documented by FastAPI OpenAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

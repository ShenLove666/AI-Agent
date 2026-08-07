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

API_CALL_RE = re.compile(
    r"""
    \bapi\.(?P<method>get|post|put|patch|delete)\s*
    (?:<[^;]*?>\s*)?
    \(\s*(?P<quote>[\"'`])
    (?P<path>(?:\\.|(?! (?P=quote) ).)*?)
    (?P=quote)
    """,
    re.DOTALL | re.VERBOSE,
)
TEMPLATE_PARAMETER_RE = re.compile(r"\$\{[^}]+\}")
OPENAPI_PARAMETER_RE = re.compile(r"\{[^}]+\}")


@dataclass(frozen=True, order=True)
class ApiCall:
    method: str
    path: str


def normalize_path(path: str) -> str:
    """Normalize frontend and OpenAPI paths into a common comparison form."""
    normalized = path.split("?", 1)[0].split("#", 1)[0]
    normalized = TEMPLATE_PARAMETER_RE.sub("{}", normalized)
    normalized = OPENAPI_PARAMETER_RE.sub("{}", normalized)
    if normalized == API_PREFIX:
        return "/"
    if normalized.startswith(f"{API_PREFIX}/"):
        return normalized[len(API_PREFIX) :]
    return normalized


def extract_service_calls(paths: Sequence[Path]) -> set[ApiCall]:
    """Extract literal axios calls from the deliberately scoped active services."""
    calls: set[ApiCall] = set()
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for match in API_CALL_RE.finditer(source):
            calls.add(ApiCall(match.group("method").upper(), normalize_path(match.group("path"))))
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

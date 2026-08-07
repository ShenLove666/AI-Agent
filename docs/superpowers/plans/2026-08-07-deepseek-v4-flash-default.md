# DeepSeek V4 Flash Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `deepseek-v4-flash` the default DeepSeek model for both ordinary and deep-thinking requests while preserving environment overrides.

**Architecture:** Keep the existing `Settings.model_endpoints()` configuration boundary and router behavior. Change only its two fallback values, protect the observable endpoint configuration with a focused test, and update the operator documentation.

**Tech Stack:** Python 3.12, pytest, environment-based configuration, Markdown.

## Global Constraints

- Default ordinary and reasoning model: `deepseek-v4-flash`.
- `DEEPSEEK_MODEL` and `DEEPSEEK_REASONING_MODEL` must continue to override defaults independently.
- Do not change Base URL, API-key loading, endpoint priority, backup providers, or request protocol.
- Modify files only under `D:\Project\rag-project`.

---

### Task 1: Upgrade the DeepSeek defaults

**Files:**
- Modify: `tests/test_architecture.py`
- Modify: `app/framework/config.py:89-100`
- Modify: `README.md:65-100`

**Interfaces:**
- Consumes: `Settings.model_endpoints() -> list[ModelEndpoint]` and the existing `ModelEndpoint.model` / `reasoning_model` fields.
- Produces: a DeepSeek endpoint whose unconfigured ordinary and reasoning model values are both `deepseek-v4-flash`.

- [ ] **Step 1: Write the failing configuration test**

Add a pytest test that clears `DEEPSEEK_MODEL` and `DEEPSEEK_REASONING_MODEL`, sets a dummy `DEEPSEEK_API_KEY`, calls `Settings().model_endpoints()`, selects the endpoint named `deepseek`, and asserts literal values:

```python
def test_deepseek_defaults_to_v4_flash_for_chat_and_reasoning(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_REASONING_MODEL", raising=False)

    endpoint = next(
        item for item in Settings().model_endpoints() if item.name == "deepseek"
    )

    assert endpoint.model == "deepseek-v4-flash"
    assert endpoint.reasoning_model == "deepseek-v4-flash"
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run `python -m pytest tests/test_architecture.py::test_deepseek_defaults_to_v4_flash_for_chat_and_reasoning -q`.

Expected: FAIL because the old defaults are `deepseek-chat` and `deepseek-reasoner`.

- [ ] **Step 3: Implement the minimal configuration change**

In the DeepSeek `ModelEndpoint`, use:

```python
model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
reasoning_model=os.getenv(
    "DEEPSEEK_REASONING_MODEL", "deepseek-v4-flash"
),
```

- [ ] **Step 4: Verify GREEN and environment overrides**

Run the focused test. Also add an assertion using explicit custom environment values so future code cannot accidentally ignore operator overrides.

- [ ] **Step 5: Update operator documentation**

Change the README PowerShell example to:

```powershell
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
$env:DEEPSEEK_REASONING_MODEL = "deepseek-v4-flash"
```

Explain that V4 Flash supports both modes and that environment variables remain optional overrides.

- [ ] **Step 6: Run verification**

Run:

```powershell
python -m pytest tests/test_architecture.py -q
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
git diff --check
```

Expected: focused tests and canonical verification pass; no whitespace errors.

- [ ] **Step 7: Commit and push**

```powershell
git add app/framework/config.py tests/test_architecture.py README.md docs/superpowers/plans/2026-08-07-deepseek-v4-flash-default.md
git commit -m "feat: default to DeepSeek V4 Flash"
git push origin main
```


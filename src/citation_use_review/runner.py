"""Launch one isolated Codex role with durable claim and terminal records."""

# Standard-library imports manage subprocesses, retries, temporary workspaces, and typed records.
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Mapping

from .contracts import validate_classification
from .errors import AgentExecutionError, ContractError, UnknownInFlightError
from .prompting import prompt_contract
from .util import atomic_write_json, load_json, reject_duplicate_keys, resolve_project_path, utc_now, write_exclusive_json


MAX_STDOUT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 16 * 1024 * 1024


def _agent_environment() -> dict[str, str]:
    """Build a minimal environment for the isolated Codex subprocess.

    Returns:
        Allowlisted authentication, certificate, proxy, and executable-location
        variables. Unrelated environment variables are not forwarded.
    """

    allowed = (
        "PATH",
        "HOME",
        "CODEX_HOME",
        "OPENAI_API_KEY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["NO_COLOR"] = "1"
    return environment


def preflight_codex(config: Mapping[str, Any]) -> str:
    """Verify the configured Codex executable and optional exact version pin.

    Args:
        config: Workflow configuration containing an ``agents`` object.

    Returns:
        Observed one-line Codex CLI version.

    Raises:
        ContractError: If the executable is unavailable or its version differs
            from an explicit nonempty pin.
    """

    agents = config.get("agents")
    if not isinstance(agents, Mapping):
        raise ContractError("config.agents must be an object")
    command = str(agents.get("command") or "codex")
    try:
        completed = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ContractError(f"cannot execute {command} --version") from error
    observed = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not observed:
        raise ContractError("Codex version preflight failed")
    version = observed[-1].strip()
    expected = str(agents.get("expected_codex_cli_version") or "").strip()
    if expected and version != expected:
        raise ContractError(f"Codex version mismatch: expected {expected!r}, observed {version!r}")
    return version


def build_codex_command(
    *,
    config: Mapping[str, Any],
    schema_path: Path,
    working_directory: Path,
) -> list[str]:
    """Build the content-free Codex CLI command for one logical role attempt.

    Args:
        config: Workflow configuration.
        schema_path: Exact output schema supplied to Codex.
        working_directory: Empty read-only-oriented workspace for the subprocess.

    Returns:
        Ordered subprocess argument vector. Prompt and article text are not part
        of the argument vector; they are supplied on standard input.
    """

    agents = config["agents"]
    command = [str(agents.get("command") or "codex"), "-a", "never", "exec", "--strict-config"]
    features = agents.get("disable_features", [])
    if not isinstance(features, list) or not all(isinstance(item, str) and item for item in features):
        raise ContractError("agents.disable_features must be a string list")
    for feature in features:
        command.extend(["--disable", feature])
    command.extend(
        [
            "--model",
            str(agents["model"]),
            "-c",
            f'model_reasoning_effort="{agents["reasoning_effort"]}"',
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--json",
            "--color",
            "never",
            "-C",
            str(working_directory),
            "-",
        ]
    )
    return command


def parse_codex_jsonl(text: str) -> tuple[dict[str, Any], int | None, bool]:
    """Extract the final agent JSON from a strict Codex ``exec --json`` stream.

    Args:
        text: Complete bounded stdout text.

    Returns:
        ``(classification, total_tokens, rate_limited)``.

    Raises:
        AgentExecutionError: If events are malformed, incomplete, failed, or do
            not contain one parseable final agent message.
    """

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise AgentExecutionError("Codex returned an empty JSONL stream")
    final_messages: list[str] = []
    turn_completed = False
    turn_failed = False
    total_tokens: int | None = None
    rate_limited = False
    for line in lines:
        try:
            event = json.loads(line, object_pairs_hook=reject_duplicate_keys)
        except (json.JSONDecodeError, ContractError) as error:
            raise AgentExecutionError("Codex returned malformed JSONL") from error
        if not isinstance(event, Mapping) or not isinstance(event.get("type"), str):
            raise AgentExecutionError("Codex JSONL contains an untyped event")
        event_type = event["type"]
        if event_type == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping) and item.get("type") == "agent_message":
                message = item.get("text")
                if not isinstance(message, str):
                    raise AgentExecutionError("agent_message event lacks text")
                final_messages.append(message)
        elif event_type == "turn.completed":
            turn_completed = True
            usage = event.get("usage")
            if isinstance(usage, Mapping):
                candidate = usage.get("total_tokens")
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
                    total_tokens = candidate
                elif all(isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool) for key in ("input_tokens", "output_tokens")):
                    total_tokens = int(usage["input_tokens"]) + int(usage["output_tokens"])
        elif event_type == "turn.failed":
            turn_failed = True
        if event_type in {"error", "turn.failed"}:
            bounded = json.dumps(event, sort_keys=True)[:4000].lower()
            rate_limited = rate_limited or "429" in bounded or "rate_limit" in bounded or "too many requests" in bounded
    if turn_failed or not turn_completed or len(final_messages) != 1:
        kind = "rate limit" if rate_limited else "incomplete or failed turn"
        raise AgentExecutionError(f"Codex produced an {kind}")
    try:
        decoded = json.loads(final_messages[0], object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, ContractError) as error:
        raise AgentExecutionError("final agent message is not one unambiguous JSON object") from error
    if not isinstance(decoded, dict):
        raise AgentExecutionError("final agent message must be one JSON object")
    return decoded, total_tokens, rate_limited


def _diagnostics(value: str) -> dict[str, Any]:
    """Return content-free diagnostics for a captured subprocess stream.

    Args:
        value: Captured stdout or stderr text.

    Returns:
        Byte count, SHA-256 digest, and line count. Raw content is omitted.
    """

    encoded = value.encode("utf-8", errors="replace")
    return {
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "line_count": len(value.splitlines()),
    }


def _load_terminal(
    *,
    terminal_path: Path,
    contract: Mapping[str, Any],
    capsule: Mapping[str, Any],
    codebook: Mapping[str, Any],
) -> dict[str, Any]:
    """Read and revalidate an existing immutable role terminal.

    Args:
        terminal_path: Existing terminal JSON path.
        contract: Recomputed role contract.
        capsule: Current validated capsule.
        codebook: Current frozen codebook.

    Returns:
        Revalidated terminal mapping.
    """

    terminal = load_json(terminal_path)
    if not isinstance(terminal, dict) or terminal.get("contract") != dict(contract):
        raise ContractError(f"stale or malformed terminal: {terminal_path}")
    if terminal.get("terminal_status") == "SUCCESS":
        terminal["result"] = validate_classification(terminal.get("result"), capsule, codebook)
    elif terminal.get("terminal_status") != "FAILED":
        raise ContractError(f"unknown role terminal status in {terminal_path}")
    return terminal


def run_codex_role(
    *,
    project_root: Path,
    config: Mapping[str, Any],
    capsule: Mapping[str, Any],
    codebook: Mapping[str, Any],
    prompt: str,
    role: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Run or safely resume one logical Codex reviewer role.

    Args:
        project_root: Repository root used for configured paths.
        config: Workflow configuration.
        capsule: Validated one-study capsule.
        codebook: Frozen scientific codebook.
        prompt: Fully assembled single-study prompt.
        role: Stable role name such as ``classifier`` or ``reviewer``.
        output_directory: Private role-specific state directory.

    Returns:
        Immutable terminal record with ``SUCCESS`` and a validated result, or
        ``FAILED`` with content-free attempt diagnostics.

    Raises:
        UnknownInFlightError: If a prior claim exists without a terminal, so a
            repeated external transmission cannot be proven safe.
        ContractError: If existing state or configuration is stale.
    """

    paths = config["paths"]
    schema_path = resolve_project_path(project_root, str(paths["classification_schema"]))
    prompt_bytes = len(prompt.encode("utf-8"))
    prompt_limit = int(config["agents"].get("max_prompt_bytes", 640_000))
    if prompt_limit < 1 or prompt_bytes > prompt_limit:
        raise ContractError(f"assembled prompt is {prompt_bytes} bytes; configured limit is {prompt_limit}")
    contract = prompt_contract(project_root, config, capsule, role, prompt)
    contract.update(
        {
            "study_id": capsule["study"]["study_id"],
            "model": str(config["agents"]["model"]),
            "reasoning_effort": str(config["agents"]["reasoning_effort"]),
        }
    )
    role_directory = output_directory.resolve()
    claim_path = role_directory / "claim.json"
    terminal_path = role_directory / "terminal.json"
    if terminal_path.exists():
        return _load_terminal(terminal_path=terminal_path, contract=contract, capsule=capsule, codebook=codebook)
    if claim_path.exists():
        claim = load_json(claim_path)
        if not isinstance(claim, Mapping) or claim.get("contract") != contract:
            raise ContractError(f"stale or malformed claim: {claim_path}")
        raise UnknownInFlightError(f"claim exists without terminal; refusing to resend role {role}")
    claim = {"claim_version": "1.0.0", "created_at": utc_now(), "contract": contract}
    try:
        write_exclusive_json(claim_path, claim)
    except FileExistsError as error:
        raise UnknownInFlightError(f"another process claimed role {role}") from error
    agents = config["agents"]
    attempts_allowed = int(agents.get("max_retries", 2)) + 1
    if attempts_allowed < 1 or attempts_allowed > 10:
        raise ContractError("agents.max_retries must produce 1-10 total attempts")
    timeout = float(agents.get("timeout_seconds", 900))
    backoff = float(agents.get("retry_backoff_seconds", 1.0))
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, attempts_allowed + 1):
        started_at = utc_now()
        error_kind = ""
        token_count: int | None = None
        rate_limited = False
        returncode: int | None = None
        stdout = ""
        stderr = ""
        try:
            with tempfile.TemporaryDirectory(prefix="citation-use-agent-") as temporary:
                working_directory = Path(temporary)
                command = build_codex_command(config=config, schema_path=schema_path, working_directory=working_directory)
                completed = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    cwd=working_directory,
                    env=_agent_environment(),
                )
            returncode = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            if len(stdout.encode("utf-8", errors="replace")) > MAX_STDOUT_BYTES or len(stderr.encode("utf-8", errors="replace")) > MAX_STDERR_BYTES:
                raise AgentExecutionError("agent output exceeded the bounded stream limit")
            if returncode != 0:
                raise AgentExecutionError("Codex process returned a nonzero exit status")
            decoded, token_count, rate_limited = parse_codex_jsonl(stdout)
            result = validate_classification(decoded, capsule, codebook)
            attempt_record = {
                "attempt": attempt,
                "started_at": started_at,
                "ended_at": utc_now(),
                "returncode": returncode,
                "error_kind": "",
                "rate_limited": rate_limited,
                "token_count": token_count,
                "stdout": _diagnostics(stdout),
                "stderr": _diagnostics(stderr),
            }
            attempts.append(attempt_record)
            terminal = {
                "terminal_version": "1.0.0",
                "terminal_status": "SUCCESS",
                "contract": contract,
                "attempts": attempts,
                "result": result,
            }
            atomic_write_json(terminal_path, terminal)
            return terminal
        except subprocess.TimeoutExpired:
            error_kind = "TIMEOUT"
        except AgentExecutionError as error:
            error_kind = "RATE_LIMIT" if "rate limit" in str(error).lower() else "PROCESS_OR_OUTPUT_ERROR"
            rate_limited = error_kind == "RATE_LIMIT"
        except ContractError:
            error_kind = "INVALID_CLASSIFICATION"
        except (OSError, ValueError, TypeError):
            error_kind = "LAUNCH_ERROR"
        attempts.append(
            {
                "attempt": attempt,
                "started_at": started_at,
                "ended_at": utc_now(),
                "returncode": returncode,
                "error_kind": error_kind,
                "rate_limited": rate_limited,
                "token_count": token_count,
                "stdout": _diagnostics(stdout),
                "stderr": _diagnostics(stderr),
            }
        )
        if attempt < attempts_allowed:
            time.sleep(max(0.0, backoff) * (2 ** (attempt - 1)))
    terminal = {
        "terminal_version": "1.0.0",
        "terminal_status": "FAILED",
        "contract": contract,
        "attempts": attempts,
        "result": None,
    }
    atomic_write_json(terminal_path, terminal)
    return terminal

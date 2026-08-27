"""Test the isolated Codex command, JSONL parser, and durable role resume."""

# Standard-library imports serialize fixtures, manage temporary state, and mock subprocesses.
import json
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

# Package imports exercise the runner without making an external model call.
from citation_use_review.errors import AgentExecutionError, ContractError
from citation_use_review.runner import build_codex_command, parse_codex_jsonl, run_codex_role
from citation_use_review.util import load_json


ROOT = Path(__file__).resolve().parents[1]


def _jsonl_for_result(result: dict[str, object]) -> str:
    """Create a minimal successful Codex JSONL stream for one result.

    Args:
        result: Classification object placed in the final agent message.

    Returns:
        Newline-delimited event stream accepted by the public parser.
    """

    events = [
        {"type": "thread.started", "thread_id": "synthetic-thread"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}},
        {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}},
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


class RunnerTests(unittest.TestCase):
    """Verify content-free invocation and exactly-once resume boundaries."""

    def setUp(self) -> None:
        """Load the public synthetic fixtures used by the mocked execution."""

        self.config = load_json(ROOT / "config/example_config.json")
        self.codebook = load_json(ROOT / "codebook/citation_use_codebook.json")
        self.capsule = load_json(ROOT / "examples/example_study_capsule.json")
        self.result = load_json(ROOT / "examples/example_classification.json")

    def test_command_is_read_only_and_schema_bound(self) -> None:
        """The external agent command should use read-only sandboxing and the frozen schema."""

        command = build_codex_command(
            config=self.config,
            schema_path=ROOT / "schemas/classification.schema.json",
            working_directory=ROOT,
        )
        self.assertEqual(command[:4], ["codex", "-a", "never", "exec"])
        self.assertIn("read-only", command)
        self.assertIn(str(ROOT / "schemas/classification.schema.json"), command)
        self.assertEqual(command[-1], "-")

    def test_jsonl_parser_extracts_result_and_usage(self) -> None:
        """A completed typed event stream should yield the final result and token count."""

        decoded, tokens, rate_limited = parse_codex_jsonl(_jsonl_for_result(self.result))
        self.assertEqual(decoded, self.result)
        self.assertEqual(tokens, 120)
        self.assertFalse(rate_limited)

    def test_jsonl_parser_rejects_multiple_agent_messages(self) -> None:
        """More than one final agent message is ambiguous and must fail closed."""

        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(self.result)}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(self.result)}},
            {"type": "turn.completed", "usage": {"total_tokens": 20}},
        ]
        with self.assertRaises(AgentExecutionError):
            parse_codex_jsonl("\n".join(json.dumps(event) for event in events))

    def test_terminal_resume_does_not_repeat_subprocess(self) -> None:
        """A validated terminal should be reused without another external transmission."""

        completed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout=_jsonl_for_result(self.result),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "classifier"
            with mock.patch("citation_use_review.runner.subprocess.run", return_value=completed) as mocked:
                first = run_codex_role(
                    project_root=ROOT,
                    config=self.config,
                    capsule=self.capsule,
                    codebook=self.codebook,
                    prompt="synthetic prompt",
                    role="classifier",
                    output_directory=output,
                )
                second = run_codex_role(
                    project_root=ROOT,
                    config=self.config,
                    capsule=self.capsule,
                    codebook=self.codebook,
                    prompt="synthetic prompt",
                    role="classifier",
                    output_directory=output,
                )
        self.assertEqual(first, second)
        self.assertEqual(first["terminal_status"], "SUCCESS")
        self.assertEqual(mocked.call_count, 1)

    def test_prompt_limit_fails_before_claim_or_subprocess(self) -> None:
        """Oversized assembled prompts must stop before durable transmission state."""

        config = copy.deepcopy(self.config)
        config["agents"]["max_prompt_bytes"] = 1
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "classifier"
            with mock.patch("citation_use_review.runner.subprocess.run") as mocked:
                with self.assertRaises(ContractError):
                    run_codex_role(
                        project_root=ROOT,
                        config=config,
                        capsule=self.capsule,
                        codebook=self.codebook,
                        prompt="too long",
                        role="classifier",
                        output_directory=output,
                    )
            self.assertFalse((output / "claim.json").exists())
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()

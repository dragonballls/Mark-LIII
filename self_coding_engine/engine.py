from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


class CodingEngineError(RuntimeError):
    """Raised when a self-coding run cannot proceed safely."""


@dataclass(frozen=True)
class CodingStep:
    id: str
    description: str
    expected_paths: tuple[str, ...]
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodingPlan:
    goal: str
    steps: tuple[CodingStep, ...]


@dataclass(frozen=True)
class CodingAttempt:
    number: int
    success: bool
    changed_paths: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class CodingEvent:
    type: str
    data: Mapping[str, Any] = field(default_factory=dict)


Planner = Callable[[str, Sequence[Mapping[str, Any]]], CodingPlan]
Executor = Callable[[CodingStep, Path, Sequence[Mapping[str, Any]]], Any]
Verifier = Callable[[CodingStep, Path], bool | Mapping[str, Any]]
Repairer = Callable[[CodingStep, int, Any, Path], Any]


class _WorkspaceTransaction:
    """Snapshot authorized files and restore them on failed attempts."""

    def __init__(self, workspace: Path, expected_paths: Iterable[str]) -> None:
        self.workspace = workspace.resolve()
        self.expected = tuple(self._safe(path) for path in expected_paths)
        self._temp = Path(tempfile.mkdtemp(prefix="self-coding-"))
        self._snapshots: dict[str, bytes | None] = {}
        for path in self.expected:
            key = str(path.relative_to(self.workspace)).replace("\\", "/")
            self._snapshots[key] = path.read_bytes() if path.is_file() else None

    def _safe(self, value: str) -> Path:
        target = Path(value)
        if not target.is_absolute():
            target = self.workspace / target
        target = target.resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise CodingEngineError(f"Path escapes workspace: {value}") from exc
        return target

    def changed_paths(self) -> tuple[str, ...]:
        changed: list[str] = []
        for path in self.expected:
            rel = str(path.relative_to(self.workspace)).replace("\\", "/")
            current = path.read_bytes() if path.is_file() else None
            if current != self._snapshots[rel]:
                changed.append(rel)
        return tuple(sorted(changed))

    def rollback(self) -> None:
        for relative, data in self._snapshots.items():
            path = self.workspace / relative
            if data is None:
                if path.exists() and path.is_file():
                    path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def close(self) -> None:
        shutil.rmtree(self._temp, ignore_errors=True)


class SelfCodingEngine:
    """Framework-independent bounded self-coding orchestration.

    The host application supplies planning, execution, verification, and optional
    repair callbacks. This layer owns workspace confinement, authorized paths,
    rollback, bounded retries, and event flow.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        repairer: Repairer | None = None,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.repairer = repairer
        self.max_attempts = int(max_attempts)

    @staticmethod
    def _workspace(path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise CodingEngineError(f"Workspace does not exist: {root}")
        return root

    @staticmethod
    def _git_status(workspace: Path) -> set[str]:
        if not (workspace / ".git").exists():
            return set()
        result = subprocess.run(
            ["git", "-C", str(workspace), "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CodingEngineError("git status failed")
        paths: set[str] = set()
        for line in result.stdout.splitlines():
            if len(line) >= 4:
                paths.add(line[3:].replace("\\", "/"))
        return paths

    def run(
        self,
        goal: str,
        *,
        workspace: str | Path,
        context: Sequence[Mapping[str, Any]] = (),
    ) -> Iterable[CodingEvent]:
        root = self._workspace(workspace)
        if not str(goal).strip():
            raise CodingEngineError("goal is required")

        baseline = self._git_status(root)
        plan = self.planner(goal, context)
        if not plan.steps:
            raise CodingEngineError("planner returned no coding steps")

        yield CodingEvent("plan", {"goal": plan.goal, "steps": [s.__dict__ for s in plan.steps]})

        attempts: list[CodingAttempt] = []
        for step in plan.steps:
            if not step.expected_paths:
                raise CodingEngineError(f"step {step.id} has no explicit authorized paths")
            transaction = _WorkspaceTransaction(root, step.expected_paths)
            previous_result: Any = None
            success = False
            try:
                for attempt_number in range(1, self.max_attempts + 1):
                    yield CodingEvent("attempt_started", {"step": step.id, "attempt": attempt_number})
                    try:
                        previous_result = self.executor(step, root, context)
                        verified = self.verifier(step, root)
                        verified_ok = bool(verified.get("success", False)) if isinstance(verified, Mapping) else bool(verified)
                        actual = self._git_status(root)
                        new_changes = actual - baseline
                        expected = {
                            str(Path(p)).replace("\\", "/").lstrip("./")
                            for p in step.expected_paths
                        }
                        unexpected = new_changes - expected
                        if unexpected:
                            raise CodingEngineError(
                                "workspace contains unauthorized repository changes: "
                                + ", ".join(sorted(unexpected))
                            )
                        if not verified_ok:
                            raise CodingEngineError("coding verification failed")
                        success = True
                        changed = transaction.changed_paths()
                        attempts.append(CodingAttempt(attempt_number, True, changed))
                        yield CodingEvent(
                            "attempt_completed",
                            {"step": step.id, "attempt": attempt_number, "changed_paths": changed},
                        )
                        break
                    except Exception as exc:
                        error = str(exc)
                        transaction.rollback()
                        attempts.append(CodingAttempt(attempt_number, False, (), error))
                        yield CodingEvent(
                            "attempt_failed",
                            {"step": step.id, "attempt": attempt_number, "error": error},
                        )
                        if attempt_number < self.max_attempts and self.repairer is not None:
                            previous_result = self.repairer(
                                step,
                                attempt_number + 1,
                                previous_result or {"error": error},
                                root,
                            )
                        elif attempt_number >= self.max_attempts:
                            raise CodingEngineError(
                                f"step {step.id} exhausted repair attempts: {error}"
                            ) from exc
            finally:
                transaction.close()

            if not success:
                raise CodingEngineError(f"step {step.id} did not complete")
            yield CodingEvent("step_completed", {"step": step.id})

        yield CodingEvent(
            "completed",
            {"goal": goal, "attempts": [a.__dict__ for a in attempts]},
        )


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

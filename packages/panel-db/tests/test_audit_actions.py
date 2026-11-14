"""Every audit action written by the code base is registered in ``AUDIT_ACTIONS``."""

import ast
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.db import audit
from payamakyar.db.audit import AUDIT_ACTIONS, record

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for base in ("apps", "packages") for p in (ROOT / base).glob("*/src/**/*.py"))


def _constants(node: ast.expr | None) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _constants(node.body) + _constants(node.orelse)
    return []


def _used_actions() -> dict[str, str]:
    """action -> first file, from ``record(action=...)``, ``_audit_user(s, u, r, "...")`` and
    ``action = "..." [if ... else "..."]``."""
    found: dict[str, str] = {}
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            values: list[str] = []
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name == "record":
                    for kw in node.keywords:
                        if kw.arg == "action":
                            values += _constants(kw.value)
                if name == "_audit_user" and len(node.args) >= 4:
                    values += _constants(node.args[3])
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "action" for t in node.targets
            ):
                values += _constants(node.value)
            for v in values:
                found.setdefault(v, str(path.relative_to(ROOT)))
    return found


def test_sources_found() -> None:
    assert len(SOURCES) > 20


def test_every_used_action_is_registered() -> None:
    used = _used_actions()
    assert "user.login" in used and "user.lock" in used  # the scan sees the call sites
    unknown = {a: f for a, f in used.items() if a not in AUDIT_ACTIONS}
    assert unknown == {}


def test_every_registered_action_is_used() -> None:
    assert set(AUDIT_ACTIONS) - set(_used_actions()) == set()


@pytest.mark.integration
async def test_record_rejects_unknown_action(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unknown audit action"):
        await record(
            db_session,
            actor_id=None,
            actor_ip=None,
            action="no.such_action",
            target_type="x",
            target_id=None,
        )
    assert audit.AUDIT_ACTIONS is AUDIT_ACTIONS

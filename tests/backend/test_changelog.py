"""CHANGELOG 一文件一防线：里程碑、测试引用与后续提交同步纪律。"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"

MILESTONES = (
    "## 未发布",
    "## 2026-07-12 · 交付队列 1–7",
    "## 2026-07-11 · 确定性运营闭环",
    "## 2026-07-11 · 原子持久化修复",
    "## 2026-07-11 · 五方法三层可运行基线",
)
REQUIRED_CAPABILITIES = (
    "五档立场刻度",
    "确定性决策纪要",
    "可追溯命令行",
    "Docker 一键复现",
    "风控三视角点评",
    "新闻 point-in-time 前置契约",
    "CHANGELOG 纪律",
)

ENTRY_RE = re.compile(r"(?ms)^- \*\*.+?(?=^- \*\*|^## |\Z)")
REFERENCE_RE = re.compile(
    r"`((?:tests/backend/[^`]+\.py|frontend/e2e/[^`]+\.spec\.ts)::[^`]+)`"
)
ADDED_ENTRY_RE = re.compile(r"(?ms)^\+- \*\*.+?(?=^\+- \*\*|\Z)")

PRODUCT_PREFIXES = (
    "backend/app/",
    "frontend/src/",
    "frontend/public/",
    "scripts/",
    "data/demo/",
)
PRODUCT_FILES = {
    ".dockerignore",
    "Dockerfile",
    "compose.yaml",
    "Makefile",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.node.json",
    "frontend/vite.config.ts",
}


def _changelog_text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout


def _has_product_change(paths: list[str]) -> bool:
    return any(
        path in PRODUCT_FILES or path.startswith(PRODUCT_PREFIXES)
        for path in paths
    )


def _added_entry_has_acceptance_reference(diff: str) -> bool:
    for entry in ADDED_ENTRY_RE.findall(diff):
        added_text = "\n".join(
            line[1:] for line in entry.splitlines() if line.startswith("+")
        )
        if "验收：" in added_text and REFERENCE_RE.search(added_text):
            return True
    return False


def test_completed_milestones_are_backfilled_in_reverse_chronological_order():
    text = _changelog_text()
    positions = [text.index(heading) for heading in MILESTONES]

    assert positions == sorted(positions)
    assert all(text.count(heading) == 1 for heading in MILESTONES)
    for capability in REQUIRED_CAPABILITIES:
        assert f"**{capability}**" in text


def test_every_changelog_entry_has_resolvable_acceptance_test():
    entries = ENTRY_RE.findall(_changelog_text())
    assert len(entries) >= 15, "历史里程碑不得被缩成不可审计摘要"

    for entry in entries:
        title = entry.split("**", 2)[1]
        references = REFERENCE_RE.findall(entry)
        assert "验收：" in entry, f"{title} 缺少验收字段"
        assert references, f"{title} 没有 path::test_name/title 引用"

        for reference in references:
            relative_path, test_name = reference.split("::", 1)
            path = ROOT / relative_path
            assert path.is_file(), f"{title} 引用了不存在的文件：{relative_path}"
            source = path.read_text(encoding="utf-8")

            if path.suffix == ".py":
                module = ast.parse(source, filename=str(path))
                functions = {
                    node.name
                    for node in module.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                assert test_name in functions, (
                    f"{title} 引用了不存在的 pytest 函数：{reference}"
                )
            else:
                title_pattern = re.compile(
                    rf"\btest\(\s*(['\"`]){re.escape(test_name)}\1"
                )
                assert title_pattern.search(source), (
                    f"{title} 引用了不存在的 Playwright 标题：{reference}"
                )


def test_product_change_range_adds_changelog_capability():
    # 无 Git 历史也能验证分类与新增条目判定；CI 再注入聚合 change range 实查。
    assert _has_product_change(["backend/app/domain/example.py"])
    assert _has_product_change(["frontend/src/App.tsx"])
    assert _has_product_change(["frontend/public/icons.svg"])
    assert _has_product_change(["frontend/index.html", ".dockerignore"])
    assert not _has_product_change(["docs/architecture.md", "tests/backend/test_x.py"])
    assert _added_entry_has_acceptance_reference(
        "+- **能力**：说明。\n"
        "+  验收：`tests/backend/test_changelog.py::"
        "test_product_change_range_adds_changelog_capability`。\n"
    )
    assert not _added_entry_has_acceptance_reference(
        "+- **能力**：只有标题，没有验收引用。\n"
    )

    base = os.getenv("CHANGELOG_BASE_SHA")
    head = os.getenv("CHANGELOG_HEAD_SHA")
    event_name = os.getenv("CHANGELOG_EVENT_NAME")
    if not base or not head or set(base) == {"0"}:
        return

    change_range = f"{base}...{head}" if event_name == "pull_request" else None
    range_args = [change_range] if change_range else [base, head]
    changed_paths = _git("diff", "--name-only", *range_args).splitlines()
    if not _has_product_change(changed_paths):
        return

    changelog_diff = _git(
        "diff", "--unified=0", *range_args, "--", "docs/CHANGELOG.md"
    )
    assert _added_entry_has_acceptance_reference(changelog_diff), (
        "本次生产代码变更必须在 docs/CHANGELOG.md 新增一个带真实验收引用的能力条目"
    )

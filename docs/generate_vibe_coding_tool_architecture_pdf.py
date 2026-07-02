from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
PDF_PATH = DOCS_DIR / "vibe_coding_tool_architecture_presentation.pdf"
MD_PATH = DOCS_DIR / "vibe_coding_tool_architecture_presentation.md"

PAGE_W = 13.333 * inch
PAGE_H = 7.5 * inch
MARGIN_X = 0.56 * inch
TOP_Y = PAGE_H - 0.52 * inch
BOTTOM_Y = 0.44 * inch


@dataclass(frozen=True)
class Palette:
    ink: colors.Color = colors.HexColor("#111827")
    muted: colors.Color = colors.HexColor("#475569")
    faint: colors.Color = colors.HexColor("#f8fafc")
    line: colors.Color = colors.HexColor("#cbd5e1")
    accent: colors.Color = colors.HexColor("#6d5dfc")
    accent_dark: colors.Color = colors.HexColor("#3f35b5")
    success: colors.Color = colors.HexColor("#0f766e")
    warning: colors.Color = colors.HexColor("#b45309")
    danger: colors.Color = colors.HexColor("#b91c1c")
    dark: colors.Color = colors.HexColor("#0f172a")


P = Palette()


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.replace("\n", " ").split()
    if not words:
        return [""]
    lines: list[str] = []
    line = words[0]
    for word in words[1:]:
        candidate = f"{line} {word}"
        if _width(candidate, font, size) <= max_width:
            line = candidate
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    *,
    font: str = "Helvetica",
    size: float = 10,
    leading: float = 13,
    fill: colors.Color = P.ink,
) -> float:
    c.setFont(font, size)
    c.setFillColor(fill)
    for line in wrap_text(text, font, size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_bullets(
    c: canvas.Canvas,
    items: Sequence[str],
    x: float,
    y: float,
    max_width: float,
    *,
    font: str = "Helvetica",
    size: float = 10,
    leading: float = 14,
    fill: colors.Color = P.ink,
    bullet_color: colors.Color = P.accent,
) -> float:
    for item in items:
        c.setFillColor(bullet_color)
        c.circle(x + 3, y + 3, 2.2, stroke=0, fill=1)
        y = draw_wrapped(
            c,
            item,
            x + 14,
            y,
            max_width - 14,
            font=font,
            size=size,
            leading=leading,
            fill=fill,
        )
        y -= 4
    return y


def draw_footer(c: canvas.Canvas, page_no: int) -> None:
    c.saveState()
    c.setStrokeColor(P.line)
    c.setLineWidth(0.5)
    c.line(MARGIN_X, 0.36 * inch, PAGE_W - MARGIN_X, 0.36 * inch)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(P.muted)
    c.drawString(MARGIN_X, 0.2 * inch, "Worktual Vibe Platform | AI coding assistant architecture")
    c.drawRightString(PAGE_W - MARGIN_X, 0.2 * inch, f"June 12, 2026 | {page_no}")
    c.restoreState()


def begin_slide(c: canvas.Canvas, page_no: int, title: str, eyebrow: str | None = None) -> float:
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(P.accent)
    c.rect(0, PAGE_H - 0.07 * inch, PAGE_W, 0.07 * inch, fill=1, stroke=0)
    if eyebrow:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(P.accent_dark)
        c.drawString(MARGIN_X, TOP_Y, eyebrow.upper())
        y = TOP_Y - 0.22 * inch
    else:
        y = TOP_Y
    c.setFont("Helvetica-Bold", 23)
    c.setFillColor(P.ink)
    c.drawString(MARGIN_X, y, title)
    draw_footer(c, page_no)
    return y - 0.38 * inch


def end_slide(c: canvas.Canvas) -> None:
    c.showPage()


def rounded_box(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: colors.Color = P.faint,
    stroke: colors.Color = P.line,
    radius: float = 8,
) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def draw_card(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str,
    *,
    accent: colors.Color = P.accent,
) -> None:
    rounded_box(c, x, y, w, h)
    c.setFillColor(accent)
    c.roundRect(x, y + h - 0.1 * inch, w, 0.1 * inch, 7, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 10.5)
    c.setFillColor(P.ink)
    c.drawString(x + 0.16 * inch, y + h - 0.32 * inch, title)
    draw_wrapped(
        c,
        body,
        x + 0.16 * inch,
        y + h - 0.52 * inch,
        w - 0.32 * inch,
        size=8.4,
        leading=10.5,
        fill=P.muted,
    )


def draw_pill(c: canvas.Canvas, x: float, y: float, text: str, *, fill: colors.Color = P.faint) -> float:
    c.setFont("Helvetica-Bold", 7.4)
    w = _width(text, "Helvetica-Bold", 7.4) + 0.28 * inch
    c.setFillColor(fill)
    c.setStrokeColor(P.line)
    c.roundRect(x, y, w, 0.22 * inch, 7, fill=1, stroke=1)
    c.setFillColor(P.ink)
    c.drawCentredString(x + w / 2, y + 0.075 * inch, text)
    return w


def draw_flow(c: canvas.Canvas, labels: Sequence[str], x: float, y: float, w: float) -> None:
    gap = 0.12 * inch
    box_w = (w - gap * (len(labels) - 1)) / len(labels)
    for index, label in enumerate(labels):
        bx = x + index * (box_w + gap)
        rounded_box(c, bx, y, box_w, 0.58 * inch, fill=colors.HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(P.accent_dark)
        c.drawString(bx + 0.1 * inch, y + 0.38 * inch, f"{index + 1:02d}")
        draw_wrapped(
            c,
            label,
            bx + 0.1 * inch,
            y + 0.24 * inch,
            box_w - 0.2 * inch,
            font="Helvetica-Bold",
            size=7.3,
            leading=8.2,
        )
        if index < len(labels) - 1:
            c.setStrokeColor(P.accent)
            c.setLineWidth(1.1)
            ax = bx + box_w
            ay = y + 0.29 * inch
            c.line(ax + 0.02 * inch, ay, ax + gap - 0.02 * inch, ay)
            c.setFillColor(P.accent)
            c.circle(ax + gap - 0.02 * inch, ay, 2, fill=1, stroke=0)


def draw_table(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    col_widths: Sequence[float],
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    row_h: float = 0.48 * inch,
) -> float:
    table_w = sum(col_widths)
    header_h = 0.33 * inch
    c.setFillColor(P.dark)
    c.roundRect(x, y_top - header_h, table_w, header_h, 6, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8.4)
    c.setFillColor(colors.white)
    tx = x
    for header, width in zip(headers, col_widths):
        c.drawString(tx + 0.08 * inch, y_top - 0.21 * inch, header)
        tx += width
    y = y_top - header_h
    for row_index, row in enumerate(rows):
        y -= row_h
        fill = colors.white if row_index % 2 == 0 else colors.HexColor("#f8fafc")
        c.setFillColor(fill)
        c.setStrokeColor(P.line)
        c.rect(x, y, table_w, row_h, fill=1, stroke=1)
        tx = x
        for cell, width in zip(row, col_widths):
            draw_wrapped(
                c,
                cell,
                tx + 0.08 * inch,
                y + row_h - 0.17 * inch,
                width - 0.16 * inch,
                size=7.1,
                leading=8.4,
                fill=P.ink,
            )
            tx += width
    return y


def write_source_markdown() -> None:
    MD_PATH.write_text(
        """# Vibe Coding Tool Architecture Presentation

## Purpose
This PDF presents a production architecture for a vibe coding tool similar to Claude Code, Cursor, Codex, Windsurf, and Aider. It is designed for engineering handoff and stakeholder presentation.

## Core Architecture
- Client surfaces: IDE extension, browser workspace, CLI, and local desktop app.
- API boundary: authenticated WebSocket/HTTP gateway that owns sessions and streams.
- Orchestrator: classifies intent, confirms risky work, creates the run plan, and coordinates agents.
- MAS runtime: planner, context, code edit, test, repair, review, security, and commit-gate agents.
- A2A protocol: typed handoffs with objective, evidence, artifacts, risk, confidence, and next action.
- Context engine: repository index, semantic search, file graph, memory retrieval, and compression.
- Tool executor: permissioned filesystem, terminal, git, package manager, browser, preview, and MCP tools.
- Validation gates: syntax, dependency preflight, build, test, preview, visual QA, security, and diff review.
- Persistence: PostgreSQL for runs and audit, Redis for live state/pub-sub, Qdrant for vectors, object storage for artifacts, and workspace storage for file snapshots.

## Required Production Behaviors
- No generated code is committed before passing validation gates.
- The backend owns authority; the model proposes plans and patches.
- Destructive or broad actions require human approval.
- Every run emits traceable lifecycle events.
- Every agent handoff is durable and replayable.
- Failures are normalized into actionable categories with repair routing.
""",
        encoding="utf-8",
    )


def slide_cover(c: canvas.Canvas, page_no: int) -> None:
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(P.accent)
    c.rect(0, PAGE_H - 0.1 * inch, PAGE_W, 0.1 * inch, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(P.accent_dark)
    c.drawString(MARGIN_X, PAGE_H - 0.9 * inch, "WORKTUAL VIBE PLATFORM")
    c.setFont("Helvetica-Bold", 36)
    c.setFillColor(P.ink)
    draw_wrapped(
        c,
        "Vibe Coding Tool Architecture",
        MARGIN_X,
        PAGE_H - 1.65 * inch,
        7.2 * inch,
        font="Helvetica-Bold",
        size=36,
        leading=39,
    )
    c.setFont("Helvetica", 13)
    c.setFillColor(P.muted)
    draw_wrapped(
        c,
        "Production workflow for AI coding assistants like Claude Code, Cursor, Codex, Windsurf, and Aider.",
        MARGIN_X,
        PAGE_H - 2.7 * inch,
        6.9 * inch,
        size=13,
        leading=17,
        fill=P.muted,
    )
    x = PAGE_W - 4.6 * inch
    y = 1.42 * inch
    rounded_box(c, x, y, 4.0 * inch, 4.7 * inch, fill=colors.HexColor("#f7f7ff"), stroke=colors.HexColor("#d8d3ff"))
    draw_card(c, x + 0.35 * inch, y + 3.42 * inch, 3.3 * inch, 0.85 * inch, "Backend Authority", "Identity, policy, tool permissions, validation, writes, and audit remain server-side.")
    draw_card(c, x + 0.35 * inch, y + 2.25 * inch, 3.3 * inch, 0.85 * inch, "MAS Runtime", "Specialist agents coordinate through typed handoffs instead of one monolithic prompt.")
    draw_card(c, x + 0.35 * inch, y + 1.08 * inch, 3.3 * inch, 0.85 * inch, "Safe Commit Gate", "Generated changes land only after build, test, preview, QA, and approval policy pass.")
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(P.muted)
    c.drawString(MARGIN_X, 0.82 * inch, "Presentation PDF | June 12, 2026")
    draw_footer(c, page_no)
    c.showPage()


def build_pdf() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    write_source_markdown()
    c = canvas.Canvas(str(PDF_PATH), pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Vibe Coding Tool Architecture Presentation")
    c.setAuthor("Worktual AI Dev")

    page = 1
    slide_cover(c, page)

    page += 1
    y = begin_slide(c, page, "Problem Analysis", "What the platform must solve")
    draw_bullets(
        c,
        [
            "Users expect natural-language coding updates, but production systems must protect the repository, runtime, credentials, and local machine.",
            "The assistant must understand project state before editing: repository graph, selected project, local folder binding, current files, prior memory, and active failure state.",
            "Slow or failed updates usually come from weak orchestration: missing budgets, unresolved dependencies, no repair routing, unclear file ownership, and unsafe write timing.",
            "The target behavior is not only code generation. It is plan, execute, validate, repair, preview, persist, explain, and allow human intervention.",
        ],
        MARGIN_X,
        y,
        6.0 * inch,
        size=10.1,
        leading=14,
    )
    draw_card(
        c,
        PAGE_W - 5.7 * inch,
        PAGE_H - 3.55 * inch,
        5.1 * inch,
        2.05 * inch,
        "Architecture Principle",
        "The model proposes. The runtime verifies. The backend commits. The user approves high-risk work. This boundary is the difference between a demo and a production coding assistant.",
        accent=P.success,
    )
    draw_card(
        c,
        PAGE_W - 5.7 * inch,
        PAGE_H - 5.95 * inch,
        5.1 * inch,
        1.75 * inch,
        "Success Criteria",
        "A run is successful only when generated or edited files pass validation gates, the preview builds, errors are normalized, events are persisted, and the UI receives a deterministic completion shape.",
        accent=P.accent,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Reference Architecture", "System boundaries")
    left_x = MARGIN_X
    right_x = PAGE_W - MARGIN_X - 3.0 * inch
    center_x = 4.55 * inch
    draw_card(c, left_x, y - 1.15 * inch, 2.9 * inch, 0.92 * inch, "Client Surfaces", "React workspace, IDE extension, CLI, local desktop, browser preview.")
    draw_card(c, left_x, y - 2.32 * inch, 2.9 * inch, 0.92 * inch, "API Gateway", "Auth, project session, WebSocket or NDJSON streaming, cancellation.")
    draw_card(c, center_x, y - 1.75 * inch, 3.8 * inch, 1.25 * inch, "Agent Orchestrator", "Intent routing, confirmation, plan graph, agent scheduling, budgets, rollback.")
    draw_card(c, center_x, y - 3.42 * inch, 3.8 * inch, 1.25 * inch, "MAS Runtime", "Planner, context, coding, test, repair, review, security, commit gate.")
    draw_card(c, right_x, y - 1.15 * inch, 3.0 * inch, 0.92 * inch, "Context Engine", "Repo index, semantic search, file graph, memory, compression.")
    draw_card(c, right_x, y - 2.32 * inch, 3.0 * inch, 0.92 * inch, "Tool Executor", "Filesystem, terminal, git, package manager, browser, MCP, preview.")
    draw_card(c, right_x, y - 3.49 * inch, 3.0 * inch, 0.92 * inch, "Data Plane", "Postgres, Redis, Qdrant, object artifacts, local workspace snapshots.")
    c.setStrokeColor(P.accent)
    c.setLineWidth(1.1)
    for sx, sy, ex, ey in [
        (left_x + 2.9 * inch, y - 0.69 * inch, center_x, y - 1.12 * inch),
        (left_x + 2.9 * inch, y - 1.86 * inch, center_x, y - 1.12 * inch),
        (center_x + 3.8 * inch, y - 1.12 * inch, right_x, y - 0.69 * inch),
        (center_x + 3.8 * inch, y - 1.12 * inch, right_x, y - 1.86 * inch),
        (center_x + 3.8 * inch, y - 2.8 * inch, right_x, y - 3.03 * inch),
    ]:
        c.line(sx, sy, ex, ey)
    draw_wrapped(
        c,
        "Boundary rule: clients render state and request actions; backend runtime owns tools, policy, validation, persistence, and final writes.",
        MARGIN_X,
        1.05 * inch,
        PAGE_W - 2 * MARGIN_X,
        font="Helvetica-Bold",
        size=10,
        leading=13,
        fill=P.ink,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "End-To-End Request Flow", "Prompt to persisted result")
    draw_flow(
        c,
        [
            "User prompt",
            "Session + project context",
            "Intent route",
            "Plan + confirmation",
            "Context retrieval",
            "Agent execution",
            "Validation gates",
            "Commit + sync",
            "UI completion",
        ],
        MARGIN_X,
        y - 0.82 * inch,
        PAGE_W - 2 * MARGIN_X,
    )
    draw_table(
        c,
        MARGIN_X,
        y - 1.55 * inch,
        [1.9 * inch, 3.15 * inch, 3.2 * inch, 3.0 * inch],
        ["Stage", "Runtime Responsibility", "Failure Case", "Expected Recovery"],
        [
            ["Route", "Classify greeting, question, new generation, scoped update, repair, or confirmation.", "Wrong route sends small chat into heavy model flow.", "Greeting/project-summary fast path, route tests, confidence threshold."],
            ["Plan", "Create bounded tasks, file scope, tool permissions, and runtime budget.", "Broad update times out during patch call.", "Split task, exact component targeting, budget-aware checkpoints."],
            ["Execute", "Run specialist agents and tools against a staged workspace.", "Generated imports or code do not build.", "Dependency preflight, repair agent, known shim policy."],
            ["Validate", "Build, test, preview, visual QA, diff review, and policy checks.", "Runtime preview crashes after build.", "Browser console capture, component smoke tests, rollback."],
            ["Commit", "Write backend files, sync selected local folder, persist memory/events.", "Generated files exist but local folder not updated.", "Explicit folder binding, write receipt, local sync audit."],
        ],
        row_h=0.56 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Component Breakdown", "Clean architecture responsibilities")
    draw_table(
        c,
        MARGIN_X,
        y,
        [2.15 * inch, 3.1 * inch, 3.05 * inch, 3.05 * inch],
        ["Component", "Owns", "Does Not Own", "Key Contracts"],
        [
            ["API Gateway", "Auth, session, project routes, streaming protocol, cancellation, request normalization.", "Prompt reasoning or file mutation policy.", "POST generate-stream, progress/error/complete events."],
            ["Orchestrator", "Intent, run graph, confirmation state, agent order, budget, rollback intent.", "Raw shell execution or direct filesystem writes.", "Run plan, action graph, agent handoff."],
            ["Context Manager", "Repo map, selected files, memories, embeddings, compression, token strategy.", "Committing edits.", "Context packet with provenance and limits."],
            ["LLM Gateway", "Provider routing, retries, model policy, structured outputs, cost and latency tracking.", "Tool authority.", "Model request, response schema, usage metrics."],
            ["Tool Executor", "Permissioned tools, filesystem, git, terminal, browser, preview, package manager.", "Planning decisions.", "Tool call, result, policy verdict, audit event."],
            ["Commit Gate", "Validation result, staged preview, write-back, local sync, version and memory persistence.", "Ignoring failed checks.", "Commit receipt, rollback reason, diff summary."],
        ],
        row_h=0.55 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "MAS Runtime Architecture", "Specialist agents, not one giant prompt")
    cards = [
        ("Planner", "Turns user intent into ordered tasks, constraints, risks, and acceptance criteria.", P.accent),
        ("Context Agent", "Builds a scoped context packet from repository, selected project, memory, and failure state.", P.success),
        ("Code Agent", "Produces patch proposals against approved files and architecture boundaries.", P.accent),
        ("Test Agent", "Selects and runs focused tests, build checks, and static validation.", P.success),
        ("Repair Agent", "Consumes structured failures and creates minimal repair attempts within budget.", P.warning),
        ("Reviewer", "Checks diff risk, API compatibility, regressions, and missing validation.", P.accent),
        ("Security Agent", "Scans secrets, prompt injection, path abuse, commands, and dependency risks.", P.danger),
        ("Commit Gate", "Commits only when validation, policy, preview, and human-approval rules pass.", P.dark),
    ]
    x0 = MARGIN_X
    y0 = y - 0.96 * inch
    w = 2.95 * inch
    h = 0.82 * inch
    for idx, (title, body, color) in enumerate(cards):
        col = idx % 4
        row = idx // 4
        draw_card(c, x0 + col * 3.08 * inch, y0 - row * 1.26 * inch, w, h, title, body, accent=color)
    draw_wrapped(
        c,
        "MAS rule: every agent emits a typed result with objective, evidence, files touched, risk, confidence, and next action. The orchestrator can replay or resume the run from these durable handoffs.",
        MARGIN_X,
        1.45 * inch,
        PAGE_W - 2 * MARGIN_X,
        font="Helvetica-Bold",
        size=10.2,
        leading=13,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "A2A Handoff Contract", "How agents communicate")
    draw_table(
        c,
        MARGIN_X,
        y,
        [2.0 * inch, 3.25 * inch, 3.2 * inch, 2.9 * inch],
        ["Field", "Meaning", "Example", "Why It Matters"],
        [
            ["source_agent / target_agent", "The sender and intended next owner.", "planner -> context_agent", "Prevents ambiguous ownership and hidden work."],
            ["objective", "Bounded work to perform next.", "Update OnboardingWizard only", "Reduces broad edits and timeout risk."],
            ["evidence", "Files, logs, errors, tests, or decisions supporting the handoff.", "Build failed: unresolved import", "Makes repair grounded, not speculative."],
            ["artifacts", "Patch, plan, test output, preview URL, screenshots, or structured validation result.", "pending diff + preview ID", "Enables replay and audit."],
            ["risk + approval", "Policy risk and whether user confirmation is required.", "High: terminal install", "Keeps destructive actions human-controlled."],
            ["confidence + next_action", "Agent confidence and a machine-readable action recommendation.", "0.72, run repair", "Supports deterministic orchestration."],
        ],
        row_h=0.5 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Context Engineering", "What enters the model")
    draw_card(c, MARGIN_X, y - 1.0 * inch, 3.75 * inch, 0.96 * inch, "Retrieved Context", "Selected files, import graph, symbols, package manifests, previous run memory, current error logs, user brief, and local-folder binding.", accent=P.success)
    draw_card(c, MARGIN_X + 4.05 * inch, y - 1.0 * inch, 3.75 * inch, 0.96 * inch, "Compressed Context", "Repository summaries, API contracts, component responsibilities, known failure signatures, and relevant test history.", accent=P.accent)
    draw_card(c, MARGIN_X + 8.1 * inch, y - 1.0 * inch, 3.75 * inch, 0.96 * inch, "Excluded Context", "Secrets, unrelated runtime folders, node_modules, generated caches, broad logs, and stale memory without provenance.", accent=P.warning)
    draw_table(
        c,
        MARGIN_X,
        y - 1.55 * inch,
        [2.35 * inch, 4.35 * inch, 4.65 * inch],
        ["Strategy", "Implementation", "Production Benefit"],
        [
            ["Repo indexing", "File tree, imports, exports, symbols, dependency manifest, test map, and route map.", "Lets updates target exact components instead of rewriting the app."],
            ["Semantic retrieval", "Qdrant embeddings over files, docs, memories, and previous successful fixes.", "Finds relevant context even when user names are imprecise."],
            ["Token budgeting", "Reserve budget for plan, patch, repair, validation summary, and final explanation.", "Prevents repair skip because runtime budget is exhausted."],
            ["Context provenance", "Every included snippet records file path, source, freshness, and why selected.", "Improves debugging and reduces stale or injected context."],
        ],
        row_h=0.54 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Tool Execution And Permissions", "Backend-owned authority")
    draw_table(
        c,
        MARGIN_X,
        y,
        [2.2 * inch, 2.7 * inch, 3.2 * inch, 3.25 * inch],
        ["Permission Tier", "Examples", "Policy", "Audit Requirement"],
        [
            ["Read-only", "List files, read project files, inspect logs, search symbols.", "Allowed inside project boundary.", "Record files read and context provenance."],
            ["Staged mutation", "Patch pending workspace, format generated files, run dependency preflight.", "Allowed only in staged copy.", "Record diff and changed files."],
            ["Runtime execution", "Build, test, preview, browser console capture, package manager checks.", "Constrained command allowlist and timeout.", "Record command, exit code, stdout/stderr summary."],
            ["Write-back", "Commit backend files, sync user-selected local folder, save versions.", "Allowed only after commit gate passes.", "Record write receipt and rollback metadata."],
            ["Human approval", "Destructive shell, broad deletion, network installs, secrets, production deploy.", "Pause and ask before execution.", "Record approver, scope, and decision."],
        ],
        row_h=0.55 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Validation And Commit Gates", "No broken code should be written")
    draw_flow(
        c,
        [
            "Artifact parse",
            "Dependency preflight",
            "Static checks",
            "Unit/build",
            "Preview build",
            "Runtime smoke",
            "Visual QA",
            "Diff review",
            "Commit gate",
        ],
        MARGIN_X,
        y - 0.8 * inch,
        PAGE_W - 2 * MARGIN_X,
    )
    draw_bullets(
        c,
        [
            "Validation must run against a staged workspace before touching the active backend project or user-selected local folder.",
            "Unresolved imports, missing packages, syntax errors, preview crashes, and console exceptions should route to repair with exact evidence.",
            "A generated file set is not complete until preview build, browser smoke, local sync, memory persistence, and UI completion all produce receipts.",
            "If any gate fails, preserve the existing website and return a normalized error with category, code, last runtime step, elapsed time, and next action.",
        ],
        MARGIN_X,
        y - 1.85 * inch,
        PAGE_W - 2 * MARGIN_X,
        size=10,
        leading=13.6,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Failure Handling And Repair Policy", "Turning failures into next actions")
    draw_table(
        c,
        MARGIN_X,
        y,
        [2.45 * inch, 3.05 * inch, 3.1 * inch, 2.75 * inch],
        ["Failure", "Likely Cause", "Repair Agent Input", "Resolution Policy"],
        [
            ["Scoped update timeout", "Patch call too broad, budget too low, unclear target component.", "File scope, task size, elapsed seconds, last model step.", "Split task or restrict exact component; never silently retry forever."],
            ["Staged Vite build failed", "Generated unresolved import, package mismatch, syntax issue.", "Full Vite log, manifest, generated diff, dependency policy.", "Repair dependency or code; commit only after rebuild."],
            ["Preview runtime crash", "Build passed but browser console/runtime state failed.", "Console stack, route, screenshot, component tree hints.", "Run browser smoke repair before write-back."],
            ["Local write-back missing", "Project not bound to selected folder or sync failed.", "Folder binding, commit receipt, file list, sync error.", "Return explicit sync failure and preserve staged artifacts."],
            ["Greeting routed to generation", "Intent classifier too aggressive.", "Prompt, project state, route confidence.", "Conversation/project-summary fast path; no Gemini artifact call or file write."],
        ],
        row_h=0.58 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Storage And Data Model", "Durable system memory")
    draw_card(c, MARGIN_X, y - 1.0 * inch, 2.7 * inch, 0.92 * inch, "PostgreSQL", "Projects, files, runs, events, messages, versions, tool calls, approvals, audit logs.", accent=P.success)
    draw_card(c, MARGIN_X + 3.0 * inch, y - 1.0 * inch, 2.7 * inch, 0.92 * inch, "Redis", "Live run state, cancellation, locks, WebSocket fanout, queue coordination.", accent=P.accent)
    draw_card(c, MARGIN_X + 6.0 * inch, y - 1.0 * inch, 2.7 * inch, 0.92 * inch, "Qdrant", "Repository embeddings, semantic memory, prior fixes, documentation retrieval.", accent=P.success)
    draw_card(c, MARGIN_X + 9.0 * inch, y - 1.0 * inch, 2.7 * inch, 0.92 * inch, "Artifact Store", "Patch bundles, generated previews, screenshots, logs, snapshots, rollback material.", accent=P.accent)
    draw_table(
        c,
        MARGIN_X,
        y - 1.55 * inch,
        [2.35 * inch, 4.35 * inch, 4.65 * inch],
        ["Entity", "Why It Exists", "Operational Requirement"],
        [
            ["GenerationRun", "Single user request lifecycle.", "Status, timestamps, route, model usage, error category, final receipt."],
            ["AgentRun / Handoff", "MAS trace and replay record.", "Source/target agent, objective, evidence, artifacts, risk, confidence."],
            ["ToolCall", "Tool audit and debugging.", "Input summary, permission tier, result, duration, stdout/stderr digest."],
            ["FileVersion", "Rollback and review.", "Before/after hash, diff, writer, validation receipt."],
            ["MemoryItem", "Project-specific learning.", "Scope, source run, freshness, confidence, invalidation policy."],
        ],
        row_h=0.48 * inch,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Scaling And Observability", "Production operation model")
    draw_bullets(
        c,
        [
            "Use WebSocket or Redis Pub/Sub for live run progress; keep HTTP endpoints for project CRUD and deterministic replay.",
            "Use distributed workers for long generation, repair, preview, browser QA, indexing, and embedding jobs.",
            "Use per-tenant and per-project locks to prevent concurrent writes from corrupting a workspace.",
            "Emit OpenTelemetry-style spans for route, plan, context retrieval, model call, tool call, validation, preview, commit, and sync.",
            "Track SLOs: time to first progress, model latency, build duration, repair success rate, preview failure rate, local sync failures, and rollback count.",
        ],
        MARGIN_X,
        y,
        6.1 * inch,
        size=10,
        leading=13.5,
    )
    draw_card(
        c,
        PAGE_W - 5.85 * inch,
        y - 1.2 * inch,
        5.25 * inch,
        1.2 * inch,
        "Multi-Tenant Controls",
        "Tenant isolation, rate limits, model quotas, encrypted secrets, workspace sandboxing, artifact retention, and audit exports are required before broad rollout.",
        accent=P.accent,
    )
    draw_card(
        c,
        PAGE_W - 5.85 * inch,
        y - 2.72 * inch,
        5.25 * inch,
        1.2 * inch,
        "Operational Dashboard",
        "Show live run graph, stuck steps, failed gates, model usage, repair attempts, preview logs, local sync receipts, and top recurring failure signatures.",
        accent=P.success,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Implementation Roadmap", "Phased delivery")
    draw_table(
        c,
        MARGIN_X,
        y,
        [1.35 * inch, 3.3 * inch, 3.55 * inch, 3.15 * inch],
        ["Phase", "Goal", "Deliverables", "Exit Criteria"],
        [
            ["1", "Stabilize current flow.", "Run locks, cancel endpoint, dependency preflight, error normalization, repair thresholds, full test/build pass.", "No stuck concurrent runs; actionable errors; baseline tests pass."],
            ["2", "Formalize MAS contracts.", "Agent contracts, A2A handoffs, commit-gate ownership, runtime summaries.", "Every action has source agent, evidence, result, and policy status."],
            ["3", "Improve context and repair.", "Repo index, targeted component retrieval, failure classifier, repair playbooks, browser console smoke.", "Scoped updates complete faster and preview failures repair reliably."],
            ["4", "Production scale.", "Queue workers, Redis Pub/Sub, Qdrant, observability dashboard, tenant quotas, artifact retention.", "Multi-user workload with traceable, isolated runs."],
        ],
        row_h=0.68 * inch,
    )
    draw_wrapped(
        c,
        "Recommendation: do not add more prompt complexity until the MAS contracts, validation receipts, and repair routing are observable end to end.",
        MARGIN_X,
        1.08 * inch,
        PAGE_W - 2 * MARGIN_X,
        font="Helvetica-Bold",
        size=10,
        leading=13,
        fill=P.danger,
    )
    end_slide(c)

    page += 1
    y = begin_slide(c, page, "Acceptance Checklist", "What must be true before launch")
    left = [
        "Greeting or small project-summary prompts never trigger file writes.",
        "Every generation/update has a durable run ID and streamed progress events.",
        "Every model/tool action has timeout, budget, retry, and cancellation behavior.",
        "Every failed run returns category, code, last step, evidence, and next action.",
        "Generated files are committed only after staged build, preview, QA, and policy pass.",
    ]
    right = [
        "Local-folder write-back uses only the user's selected folder binding.",
        "Broad or destructive actions pause for human approval.",
        "Agent handoffs are typed, replayable, and visible in debugging tools.",
        "Tests cover routing, streaming shapes, validation gates, repair, and local sync.",
        "Telemetry identifies stuck steps, repeated failure signatures, and model latency.",
    ]
    draw_bullets(c, left, MARGIN_X, y, 5.55 * inch, size=10.2, leading=14)
    draw_bullets(c, right, MARGIN_X + 6.1 * inch, y, 5.55 * inch, size=10.2, leading=14, bullet_color=P.success)
    draw_card(
        c,
        MARGIN_X,
        0.88 * inch,
        PAGE_W - 2 * MARGIN_X,
        0.72 * inch,
        "Final Architecture Position",
        "A production vibe coding tool is a controlled runtime with AI planning inside it. Treat prompts as one input to a larger verified workflow, not as the workflow itself.",
        accent=P.dark,
    )
    draw_footer(c, page)
    c.save()


if __name__ == "__main__":
    build_pdf()
    print(PDF_PATH)
    print(MD_PATH)

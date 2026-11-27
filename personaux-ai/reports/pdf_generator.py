"""ReportLab PDF output: individual persona reports and combined run reports."""
from __future__ import annotations

from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import config

PRIMARY = colors.HexColor("#0F766E")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E2E8F0")
SOFT = colors.HexColor("#F1F5F9")
SEVERITY_COLORS = {
    "Critical": colors.HexColor("#B91C1C"),
    "High": colors.HexColor("#C2410C"),
    "Medium": colors.HexColor("#A16207"),
    "Low": colors.HexColor("#1D4ED8"),
}
OUTCOME_COLORS = {"success": colors.HexColor("#15803D"), "failure": colors.HexColor("#B91C1C"),
                  "abandoned": colors.HexColor("#C2410C"), "error": colors.HexColor("#6B7280")}

_base = getSampleStyleSheet()
STYLES = {
    "title": ParagraphStyle("t", parent=_base["Title"], fontName="Helvetica-Bold", fontSize=22, textColor=INK, alignment=TA_LEFT, spaceAfter=4),
    "subtitle": ParagraphStyle("st", parent=_base["Normal"], fontSize=10.5, textColor=MUTED, spaceAfter=14),
    "h1": ParagraphStyle("h1", parent=_base["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=PRIMARY, spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=_base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=INK, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("b", parent=_base["Normal"], fontSize=9.5, leading=13, textColor=INK),
    "small": ParagraphStyle("s", parent=_base["Normal"], fontSize=8, leading=10.5, textColor=MUTED),
    "cell": ParagraphStyle("c", parent=_base["Normal"], fontSize=8.5, leading=11, textColor=INK),
    "cellb": ParagraphStyle("cb", parent=_base["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=INK),
}
PAGE_W = A4[0] - 3.6 * cm


def P(text, style="body") -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), STYLES[style])


def badge(label: str, color) -> Paragraph:
    return Paragraph(f'<font color="{color.hexval()}"><b>{escape(label)}</b></font>', STYLES["cell"])


def _table(rows, widths, header=True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT)]
    t.setStyle(TableStyle(style))
    return t


def _kv_table(pairs) -> Table:
    rows = [[P(k, "cellb"), P(v, "cell")] for k, v in pairs]
    return _table(rows, [4.2 * cm, PAGE_W - 4.2 * cm], header=False)


def _image(path: str | None, max_w: float = PAGE_W, max_h: float = 11 * cm):
    if not path or not Path(path).exists():
        return P("(screenshot unavailable)", "small")
    img = Image(path)
    ratio = min(max_w / img.imageWidth, max_h / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
    return img


def _on_page(title: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(1.8 * cm, 1.1 * cm, f"{config.APP_NAME} — {title}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(PRIMARY)
        canvas.setLineWidth(2)
        canvas.line(1.8 * cm, A4[1] - 1.2 * cm, A4[0] - 1.8 * cm, A4[1] - 1.2 * cm)
        canvas.restoreState()
    return draw


def _fmt_date(d) -> str:
    return d.strftime("%Y-%m-%d %H:%M UTC") if d else "-"


def _findings_section(findings: list[dict], include_shots: bool = True) -> list:
    out: list = []
    if not findings:
        return [P("No UX friction findings were recorded for this persona.")]
    rows = [[P("Severity", "cellb"), P("Finding", "cellb"), P("Category", "cellb"), P("Source", "cellb"), P("Step", "cellb")]]
    for f in findings:
        rows.append([badge(f["severity"], SEVERITY_COLORS.get(f["severity"], MUTED)), P(f["title"], "cell"),
                     P(f["category"], "cell"), P("Verified" if f["source"] == "verified" else "AI-inferred", "cell"),
                     P(f.get("step_number") or "-", "cell")])
    out.append(_table(rows, [2 * cm, 7.4 * cm, 3.6 * cm, 2.2 * cm, PAGE_W - 15.2 * cm]))
    out.append(Spacer(1, 8))
    for f in findings:
        block = [
            Paragraph(f'<font color="{SEVERITY_COLORS.get(f["severity"], MUTED).hexval()}"><b>[{f["severity"]}]</b></font> '
                      f'<b>{escape(f["title"])}</b>', STYLES["body"]),
            _kv_table([
                ("Persona", f["persona_name"]), ("Category", f["category"]),
                ("Type", "Objectively verified in browser" if f["source"] == "verified" else f"AI-inferred persona observation (confidence {f['confidence']:.0%})"),
                ("URL", f.get("url") or "-"), ("Description", f["description"]), ("Evidence", f["evidence"]),
                ("User impact", f["user_impact"]), ("Suggested fix", f["suggested_fix"]),
                ("Screenshot", f"Step {f.get('step_number')}" if f.get("step_number") else "-"),
            ]),
        ]
        if include_shots and f.get("screenshot_path") and f["severity"] in ("Critical", "High"):
            block.append(Spacer(1, 3))
            block.append(_image(f["screenshot_path"], max_w=10 * cm, max_h=6 * cm))
        block.append(Spacer(1, 8))
        out.append(KeepTogether(block))
    return out


def _violations_section(violations: list[dict]) -> list:
    if not violations:
        return [P("No automated accessibility violations were detected on the scanned pages. "
                  "Automated checks cover only part of WCAG; manual review is still required.")]
    grouped: dict[str, dict] = {}
    for v in violations:
        g = grouped.setdefault(v["rule_id"], {**v, "count": 0, "pages": set()})
        g["count"] += 1
        g["pages"].add(v["url"])
    rows = [[P("Severity", "cellb"), P("Rule", "cellb"), P("Description / fix", "cellb"), P("Nodes", "cellb"), P("Source", "cellb")]]
    for g in sorted(grouped.values(), key=lambda x: ["Critical", "High", "Medium", "Low"].index(x["severity"])):
        rows.append([
            badge(g["severity"], SEVERITY_COLORS.get(g["severity"], MUTED)), P(g["rule_id"], "cell"),
            P(f"{g['help_text'] or g['description']}\nExample: {g['html'][:160]}\nFix: {g['suggested_fix'][:240]}", "cell"),
            P(g["count"], "cell"), P(g["source"], "cell"),
        ])
    return [_table(rows, [2 * cm, 3.4 * cm, 9.2 * cm, 1.4 * cm, PAGE_W - 16 * cm]),
            Spacer(1, 4), P("Automated checks (axe-core and keyboard heuristics) do not establish full WCAG compliance.", "small")]


def _persona_story(data: dict, with_steps: bool = True) -> list:
    p = data["persona"]
    out: list = [P(f"{p['name']} — {p['title']}", "h1")]
    outcome = data["outcome"] or "-"
    out.append(Paragraph(
        f'Outcome: <font color="{OUTCOME_COLORS.get(outcome, MUTED).hexval()}"><b>{escape(outcome.upper())}</b></font> &nbsp; '
        f'Experience score: <b>{data["score"] if data["score"] is not None else "-"}/100</b> &nbsp; Goal progress: <b>{data["goal_progress"]}%</b>',
        STYLES["body"]))
    out.append(Spacer(1, 6))
    out.append(_kv_table([
        ("Profile", p["description"]), ("Behaviors", p.get("behaviors", "")),
        ("Interaction", f"{p.get('interaction_mode')} | zoom {int((p.get('text_zoom') or 1) * 100)}% | "
                        f"language {p.get('language_level')} | patience {p.get('patience')}/10"),
        ("Journey objective", data["journey_goal"]), ("Website", data["website_url"]),
        ("Steps", f"{data['total_steps']} total, {data['successful_steps']} succeeded, {data['failed_steps']} failed"),
        ("Duration", f"{data['duration_seconds'] or 0:.0f} s"),
        ("End / abandonment reason", data["abandonment_reason"] or "-"),
    ]))
    if data["summary"]:
        out += [P("AI experience summary", "h2"), P(data["summary"])]
    a = data.get("assessment") or {}
    if a:
        out += [P("Persona assessment", "h2"), _kv_table([
            ("Understood the site", "Yes" if a.get("understood_site") else "No"),
            ("Required action easy to find", "Yes" if a.get("action_easy_to_find") else "No"),
            ("Interaction confusing", "Yes" if a.get("interaction_confusing") else "No"),
            ("Instructions clear", "Yes" if a.get("instructions_clear") else "No"),
            ("Unnecessary steps", "Yes" if a.get("unnecessary_steps") else "No"),
        ])]
    out += [P("UX friction findings", "h2")] + _findings_section(data["findings"])
    out += [P("Accessibility findings", "h2")] + _violations_section(data["violations"])
    if data["recommendations"]:
        out.append(P("Recommended improvements", "h2"))
        for i, r in enumerate(data["recommendations"], 1):
            out.append(P(f"{i}. {r}"))
    if with_steps:
        out += [PageBreak(), P("Step-by-step execution timeline", "h2")]
        for s in data["steps"]:
            status = "OK" if s["success"] else f"FAILED — {s['error']}"
            block = [
                Paragraph(f"<b>Step {s['step_number']}: {escape(s['action'])}</b> {escape(str(s['target'] or ''))[:120]}", STYLES["body"]),
                _kv_table([
                    ("Result", status), ("URL", s["url_after"] or "-"), ("Reason", s["reason"] or "-"),
                    ("Persona observation", s["observation"] or "-"), ("Friction", s["friction_note"] or "-"),
                    ("Load time", f"{s['load_time_ms']} ms" if s["load_time_ms"] else "-"),
                    ("Time", _fmt_date(s["timestamp"])),
                ]),
                Spacer(1, 3), _image(s["screenshot_path"], max_w=12 * cm, max_h=7.5 * cm), Spacer(1, 10),
            ]
            out.append(KeepTogether(block))
    return out


def build_persona_pdf(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title=f"{config.APP_NAME} — {data['persona']['name']} report")
    story = [P(f"{config.APP_NAME} persona report", "title"),
             P(f"{config.APP_TAGLINE}  |  Run #{data['run_id']}  |  {_fmt_date(data['test_date'])}  |  {data['viewport']}", "subtitle")]
    story += _persona_story(data)
    doc.build(story, onFirstPage=_on_page(data["persona"]["name"]), onLaterPages=_on_page(data["persona"]["name"]))
    return path


def build_combined_pdf(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm, title=f"{config.APP_NAME} — combined report")
    s = data["synthesis"] or {}
    story: list = [
        P(f"{config.APP_NAME} combined UX report", "title"),
        P(config.APP_TAGLINE, "subtitle"),
        _kv_table([
            ("Project", data["project"]), ("Website URL", data["website_url"]), ("Journey goal", data["journey_goal"]),
            ("Test date", _fmt_date(data["test_date"])), ("Viewport", data["viewport"]),
            ("Personas", ", ".join(f"{p['persona']['name']} ({p['persona']['title']})" for p in data["personas"])),
        ]),
        P("Overall statistics", "h1"),
        _table([
            [P(h, "cellb") for h in ("Personas", "Successful", "Failed", "Abandoned", "UX findings", "A11y issues", "Critical")],
            [P(v, "cell") for v in (data["total_personas"], data["successful"], data["failed"], data["abandoned"],
                                    data["total_findings"], data["total_a11y"], data["critical"])],
        ], [PAGE_W / 7] * 7),
    ]
    if s.get("executive_summary"):
        story += [P("Executive summary", "h2"), P(s["executive_summary"])]
    story += [P("Persona comparison", "h1")]
    rows = [[P(h, "cellb") for h in ("Persona", "Outcome", "Progress", "Score", "Steps (ok/fail)", "Findings", "A11y", "Duration")]]
    for p in data["personas"]:
        rows.append([
            P(f"{p['persona']['name']}\n{p['persona']['title']}", "cell"),
            badge((p["outcome"] or "-").upper(), OUTCOME_COLORS.get(p["outcome"], MUTED)),
            P(f"{p['goal_progress']}%", "cell"), P(p["score"] if p["score"] is not None else "-", "cell"),
            P(f"{p['successful_steps']}/{p['failed_steps']}", "cell"), P(len(p["findings"]), "cell"),
            P(len(p["violations"]), "cell"), P(f"{p['duration_seconds'] or 0:.0f}s", "cell"),
        ])
    story.append(_table(rows, [3.4 * cm, 2.2 * cm, 1.7 * cm, 1.5 * cm, 2.3 * cm, 1.8 * cm, 1.5 * cm, PAGE_W - 14.4 * cm]))
    if data["problem_pages"]:
        story += [P("Most problematic pages", "h2"),
                  _table([[P("Page", "cellb"), P("Issues", "cellb")]] + [[P(u, "cell"), P(c, "cell")] for u, c in data["problem_pages"]],
                         [PAGE_W - 2.5 * cm, 2.5 * cm])]
    if data["common_issues"]:
        story += [P("Common issues across personas", "h2"),
                  _table([[P("Issue", "cellb"), P("Type", "cellb"), P("Personas", "cellb")]]
                         + [[P(c["issue"], "cell"), P(c["type"], "cell"), P(", ".join(c["personas"]), "cell")] for c in data["common_issues"]],
                         [9.5 * cm, 2.6 * cm, PAGE_W - 12.1 * cm])]
    if s.get("recommendations"):
        story.append(P("Prioritised recommendations", "h2"))
        for r in s["recommendations"]:
            story.append(P(f"{r['priority']}. {r['recommendation']}"))
            story.append(P(f"Why: {r['rationale']}  |  Personas: {', '.join(r.get('personas_affected', []))}", "small"))
            story.append(Spacer(1, 3))
    story.append(P("Accessibility summary", "h2"))
    story += _violations_section([v for p in data["personas"] for v in p["violations"]])
    for p in data["personas"]:
        story.append(PageBreak())
        story += _persona_story(p, with_steps=False)
        key_shots = [st for st in p["steps"] if st["screenshot_path"]][-2:]
        if key_shots:
            story.append(P("Key screenshots", "h2"))
            for st in key_shots:
                story.append(KeepTogether([P(f"Step {st['step_number']}: {st['action']} — {st['url_after']}", "small"),
                                           _image(st["screenshot_path"], max_w=11 * cm, max_h=7 * cm), Spacer(1, 6)]))
    doc.build(story, onFirstPage=_on_page("Combined report"), onLaterPages=_on_page("Combined report"))
    return path

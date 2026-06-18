"""PowerPoint generation tool — upgraded with visual styles, templates, notes, and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pptx import Presentation as PptxPresentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

SANDBOX = Path("agent_sandbox")

# ── Visual Style Presets ──


@dataclass
class StylePreset:
    name: str
    accent: RGBColor
    dark: RGBColor
    light: RGBColor
    bg: RGBColor
    title_font_size: int = 44
    slide_title_size: int = 28
    body_size: int = 18
    code_size: int = 13


STYLES: dict[str, StylePreset] = {
    "corporate": StylePreset(
        name="Corporate",
        accent=RGBColor(0x1A, 0x73, 0xE8),  # Blue
        dark=RGBColor(0x20, 0x20, 0x20),
        light=RGBColor(0xCC, 0xDD, 0xFF),
        bg=RGBColor(0xFF, 0xFF, 0xFF),
    ),
    "dark-tech": StylePreset(
        name="Dark Tech",
        accent=RGBColor(0x00, 0xCC, 0xFF),  # Cyan
        dark=RGBColor(0xE0, 0xE0, 0xE0),
        light=RGBColor(0x00, 0x66, 0x99),
        bg=RGBColor(0x1A, 0x1A, 0x2E),
    ),
    "minimal": StylePreset(
        name="Minimal",
        accent=RGBColor(0x33, 0x33, 0x33),  # Charcoal
        dark=RGBColor(0x11, 0x11, 0x11),
        light=RGBColor(0x99, 0x99, 0x99),
        bg=RGBColor(0xFA, 0xFA, 0xFA),
    ),
    "warm": StylePreset(
        name="Warm",
        accent=RGBColor(0xE8, 0x6C, 0x00),  # Orange
        dark=RGBColor(0x33, 0x22, 0x11),
        light=RGBColor(0xFF, 0xDD, 0xAA),
        bg=RGBColor(0xFF, 0xFD, 0xF5),
    ),
}

# ── Slide dimensions ──

CANVAS_FORMATS: dict[str, tuple[Any, Any]] = {
    "16:9": (Inches(13.333), Inches(7.5)),
    "4:3": (Inches(10), Inches(7.5)),
    "a4": (Inches(11.69), Inches(8.27)),
}

# ── Transitions ──

TRANSITIONS: dict[str, str] = {
    "fade": "fade",
    "push": "push",
    "wipe": "wipe",
    "cover": "cover",
    "uncover": "uncover",
    "dissolve": "dissolve",
}


def _set_slide_bg(slide, color: RGBColor) -> None:
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left: float, top: float, width: float, height: float) -> Any:
    return slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )


def _detect_layout(title: str, content: list[str]) -> str:
    text = " ".join(content).lower()
    if len(content) == 1 and len(content[0]) < 60:
        return "center_text"
    if any(w in text for w in ["question", "quiz", "?"]) and any(
        c.startswith("?") or c.startswith("*") for c in content
    ):
        return "quiz"
    if "```" in text or any(kw in text for kw in ["def ", "import ", "class ", "return "]):
        return "code"
    if text.count("\n") > 5 or max(len(c) for c in content) > 100:
        return "two_column"
    return "bullets"


def _build_slide(
    prs: Any,
    title: str,
    content: list[str],
    layout_type: str | None = None,
    notes: str | None = None,
    style: StylePreset | None = None,
    slide_w: int = 0,
    slide_h: int = 0,
):
    st = style or STYLES["corporate"]
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, st.bg)

    # Set speaker notes
    if notes:
        notes_slide = slide.notes_slide
        tf = notes_slide.notes_text_frame
        tf.text = notes

    # Title bar
    bar_w = slide_w
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), bar_w, Inches(1.0))
    bar.fill.solid()
    bar.fill.fore_color.rgb = st.accent
    bar.line.fill.background()

    tf = bar.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(st.slide_title_size)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if st.name != "Minimal" else st.dark
    p.alignment = PP_ALIGN.LEFT
    tf.margin_left = Inches(0.5)
    tf.margin_top = Inches(0.15)

    detected = layout_type or _detect_layout(title, content)
    y_start = 1.3
    margin = 0.5
    body_w = slide_w / 914400 - margin * 2

    if detected == "code":
        # Code block with gray background
        bg = slide.shapes.add_shape(
            1,
            Inches(margin - 0.2),
            Inches(y_start - 0.1),
            Inches(body_w + 0.4),
            Inches(5.7),
        )
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0xF0, 0xF0, 0xF0)
        bg.line.fill.background()

        box = _add_textbox(slide, margin, y_start, body_w, 5.5)
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = "\n".join(content)
        p.font.size = Pt(st.code_size)
        p.font.name = "Consolas"
        p.font.color.rgb = st.dark

    elif detected == "two_column":
        mid = len(content) // 2
        col_w = (body_w - margin) / 2
        for col_idx, (items, left) in enumerate(
            [(content[:mid], margin), (content[mid:], margin + col_w + margin)]
        ):
            box = _add_textbox(slide, left, y_start, col_w, 5.5)
            tf = box.text_frame
            tf.word_wrap = True
            first = True
            for item in items:
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = f"  {item}"
                p.font.size = Pt(16)
                p.font.color.rgb = st.dark
                p.space_after = Pt(6)

    elif detected == "quiz":
        box = _add_textbox(slide, margin, y_start, body_w, 5.5)
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for item in content:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            if item.startswith("?"):
                p.text = item
                p.font.size = Pt(20)
                p.font.bold = True
                p.font.color.rgb = st.accent
                p.space_after = Pt(4)
            else:
                p.text = f"  {item}"
                p.font.size = Pt(16)
                p.font.color.rgb = st.dark
                p.space_after = Pt(12)

    elif detected == "center_text":
        box = _add_textbox(slide, margin, 2.5, body_w, 3)
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = content[0]
        p.font.size = Pt(24)
        p.font.italic = True
        p.font.color.rgb = st.accent
        p.alignment = PP_ALIGN.CENTER

    else:  # bullets
        box = _add_textbox(slide, margin, y_start, body_w, 5.5)
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for item in content:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            if item.startswith("#"):
                p.text = item.lstrip("#").strip()
                p.font.size = Pt(20)
                p.font.bold = True
                p.font.color.rgb = st.accent
                p.space_after = Pt(4)
            elif item.startswith(">"):
                p.text = item.lstrip(">").strip()
                p.font.size = Pt(14)
                p.font.color.rgb = st.light
                p.font.italic = True
                p.space_after = Pt(4)
            else:
                p.text = f"  {item}"
                p.font.size = Pt(st.body_size)
                p.font.color.rgb = st.dark
                p.space_after = Pt(6)


def create_presentation_tool() -> ToolHandler:
    async def _execute(args: dict[str, Any], ctx: ToolContext | None) -> str:
        filename = args.get("filename", "presentation.pptx").strip()
        if not filename.endswith(".pptx"):
            filename += ".pptx"

        slides_data = args.get("slides", [])
        if not slides_data:
            return "ERROR: 'slides' list is required."

        title = args.get("title", "Presentation")
        subtitle = args.get("subtitle", "")
        style_name = args.get("style", "corporate").lower()
        canvas = args.get("format", "16:9").lower()
        transition = args.get("transition", "").lower()

        st = STYLES.get(style_name, STYLES["corporate"])
        dims = CANVAS_FORMATS.get(canvas, CANVAS_FORMATS["16:9"])
        slide_w, slide_h = dims

        prs = PptxPresentation()
        prs.slide_width = slide_w
        prs.slide_height = slide_h

        # ── Title slide ──
        title_slide = prs.slides.add_slide(prs.slide_layouts[6])
        _set_slide_bg(title_slide, st.accent)

        # Decorative bar at bottom
        bar = title_slide.shapes.add_shape(
            1, Inches(0), Inches(slide_h / 914400 - 0.15), slide_w, Inches(0.15)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = st.light if st.name != "Dark Tech" else RGBColor(0x00, 0x99, 0xCC)
        bar.line.fill.background()

        tf = _add_textbox(title_slide, 1, 2.0, slide_w / 914400 - 2, 2.5).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(st.title_font_size)
        p.font.bold = True
        p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        p.alignment = PP_ALIGN.CENTER

        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(22)
            p2.font.color.rgb = st.light
            p2.alignment = PP_ALIGN.CENTER

        # Date + author at bottom
        p3 = tf.add_paragraph()
        p3.text = datetime.now().strftime("%B %d, %Y")
        p3.font.size = Pt(14)
        p3.font.color.rgb = st.light
        p3.alignment = PP_ALIGN.CENTER

        # ── Content slides ──
        for slide_data in slides_data:
            slide_title = slide_data.get("title", "Slide")
            content = slide_data.get("content", [])
            layout = slide_data.get("layout")
            notes = slide_data.get("notes")
            _build_slide(
                prs,
                slide_title,
                content if isinstance(content, list) else [content],
                layout,
                notes,
                st,
                slide_w,
                slide_h,
            )

        # ── Set transition ──
        if transition in TRANSITIONS:
            for slide in prs.slides:
                slide.slide_show_transition.transition_type = TRANSITIONS[transition]

        # Save
        SANDBOX.mkdir(parents=True, exist_ok=True)
        output_path = (SANDBOX / filename).resolve()
        prs.save(str(output_path))
        return (
            f"Created presentation: {filename} "
            f"({len(slides_data) + 1} slides, style: {st.name}, format: {canvas})"
        )

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "create_presentation",
                "description": (
                    "Create a PowerPoint (.pptx) with smart layouts,"
                    " visual styles, speaker notes, and transitions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Presentation title"},
                        "subtitle": {"type": "string", "description": "Optional subtitle"},
                        "filename": {
                            "type": "string",
                            "description": "Output filename (default: presentation.pptx)",
                        },
                        "style": {
                            "type": "string",
                            "description": (
                                "Visual style: 'corporate' (blue, default),"
                                " 'dark-tech' (cyan on dark),"
                                " 'minimal' (charcoal on light),"
                                " 'warm' (orange tones)"
                            ),
                        },
                        "format": {
                            "type": "string",
                            "description": "Slide format: '16:9' (default), '4:3', 'a4'",
                        },
                        "transition": {
                            "type": "string",
                            "description": (
                                "Slide transition: 'fade', 'push', 'wipe',"
                                " 'cover', 'uncover', 'dissolve'"
                            ),
                        },
                        "slides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string", "description": "Slide title"},
                                    "content": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": (
                                            "Content items. Auto-detects:"
                                            " bullets (default), code (```, def, import),"
                                            " two_column (long content), quiz (? prefix),"
                                            " center_text (single short line)."
                                            " Use # for sub-heading, > for quote."
                                        ),
                                    },
                                    "layout": {
                                        "type": "string",
                                        "description": (
                                            "Override auto-detection:"
                                            " 'bullets', 'code', 'two_column',"
                                            " 'quiz', 'center_text'"
                                        ),
                                    },
                                    "notes": {
                                        "type": "string",
                                        "description": "Speaker notes for this slide",
                                    },
                                },
                                "required": ["title"],
                            },
                            "description": (
                                "Array of slides. Each has title, content[],"
                                " optional layout, and notes."
                            ),
                        },
                    },
                    "required": ["title", "slides"],
                },
            },
        ),
        execute=_execute,
    )

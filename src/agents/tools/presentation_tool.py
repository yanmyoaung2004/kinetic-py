"""PowerPoint generation tool — creates .pptx files with smart layout detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation as PptxPresentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from src.agents.tools.registry import ToolContext, ToolHandler
from src.types.agent import ToolDefinition

SANDBOX = Path("agent_sandbox")
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

ACCENT = RGBColor(0x1A, 0x73, 0xE8)  # Blue
DARK = RGBColor(0x20, 0x20, 0x20)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_BG = RGBColor(0xF5, 0xF5, 0xF5)


def _set_slide_bg(slide, color: RGBColor) -> None:
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_textbox(slide, left: float, top: float, width: float, height: float) -> Any:
    return slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )


def _add_paragraph(tf, text: str, size: int = 18, bold: bool = False, color: RGBColor = DARK, alignment=PP_ALIGN.LEFT):
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.alignment = alignment
    return p


def _detect_layout(title: str, content: str | list[str]) -> str:
    """Smart layout detection based on content."""
    if isinstance(content, str):
        content = [content]
    text = " ".join(content).lower()

    if "```" in text or "def " in text or "import " in text or "class " in text:
        return "code"
    if any(w in text for w in ["diagram", "architecture", "flow", "pipeline"]):
        return "two_column"
    if len(content) <= 3 and all(len(c) < 80 for c in content):
        return "bullets"
    if any(w in text for w in ["question", "quiz", "exercise"]):
        return "quiz"
    return "bullets"


def _build_slide(prs: Any, title: str, content: str | list[str], layout_type: str | None = None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_slide_bg(slide, WHITE)

    # Title bar
    bar = slide.shapes.add_shape(
        1, Inches(0), Inches(0), SLIDE_WIDTH, Inches(1.0)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()

    tf = bar.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.LEFT
    tf.margin_left = Inches(0.5)
    tf.margin_top = Inches(0.15)

    if isinstance(content, str):
        content = [content]

    detected = layout_type or _detect_layout(title, content)
    y_start = 1.3

    if detected == "code":
        box = _add_textbox(slide, 0.5, y_start, 12.3, 5.5)
        tf = box.text_frame
        tf.word_wrap = True
        code_block = "\n".join(content)
        p = tf.paragraphs[0]
        p.text = code_block
        p.font.size = Pt(13)
        p.font.name = "Consolas"
        p.font.color.rgb = DARK
        tf.margin_left = Inches(0.3)
        tf.margin_top = Inches(0.2)
        # Light gray background
        bg = slide.shapes.add_shape(
            1, Inches(0.3), Inches(y_start - 0.1), Inches(12.7), Inches(5.7)
        )
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0xF0, 0xF0, 0xF0)
        bg.line.fill.background()
        # Re-add text on top
        box2 = _add_textbox(slide, 0.5, y_start, 12.3, 5.5)
        tf2 = box2.text_frame
        tf2.word_wrap = True
        lines = "\n".join(content)
        p2 = tf2.paragraphs[0]
        p2.text = lines
        p2.font.size = Pt(13)
        p2.font.name = "Consolas"
        p2.font.color.rgb = DARK

    elif detected == "two_column":
        mid = len(content) // 2
        for col_idx, (items, left) in enumerate([(content[:mid], 0.5), (content[mid:], 6.8)]):
            box = _add_textbox(slide, left, y_start, 6.0, 5.5)
            tf = box.text_frame
            tf.word_wrap = True
            first = True
            for item in items:
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = f"• {item}"
                p.font.size = Pt(16)
                p.font.color.rgb = DARK
                p.space_after = Pt(6)

    elif detected == "quiz":
        box = _add_textbox(slide, 0.5, y_start, 12.3, 5.5)
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
                p.font.color.rgb = ACCENT
                p.space_after = Pt(4)
            else:
                p.text = f"  {item}"
                p.font.size = Pt(16)
                p.font.color.rgb = DARK
                p.space_after = Pt(12)

    else:  # bullets
        box = _add_textbox(slide, 0.5, y_start, 12.3, 5.5)
        tf = box.text_frame
        tf.word_wrap = True
        first = True
        for item in content:
            if item.startswith("#"):
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = item.lstrip("#").strip()
                p.font.size = Pt(20)
                p.font.bold = True
                p.font.color.rgb = ACCENT
                p.space_after = Pt(4)
            elif item.startswith(">"):
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = item.lstrip(">").strip()
                p.font.size = Pt(14)
                p.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
                p.font.italic = True
                p.space_after = Pt(4)
            else:
                p = tf.paragraphs[0] if first else tf.add_paragraph()
                first = False
                p.text = f"• {item}"
                p.font.size = Pt(18)
                p.font.color.rgb = DARK
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

        prs = PptxPresentation()
        prs.slide_width = SLIDE_WIDTH
        prs.slide_height = SLIDE_HEIGHT

        # Title slide
        title_slide = prs.slides.add_slide(prs.slide_layouts[6])
        _set_slide_bg(title_slide, ACCENT)
        tf = _add_textbox(title_slide, 1, 2.5, 11.3, 2).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(44)
        p.font.bold = True
        p.font.color.rgb = WHITE
        p.alignment = PP_ALIGN.CENTER

        subtitle = args.get("subtitle", "")
        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(22)
            p2.font.color.rgb = RGBColor(0xCC, 0xDD, 0xFF)
            p2.alignment = PP_ALIGN.CENTER

        for slide_data in slides_data:
            slide_title = slide_data.get("title", "Slide")
            content = slide_data.get("content", [])
            layout = slide_data.get("layout")  # optional override
            _build_slide(prs, slide_title, content, layout)

        # Save
        SANDBOX.mkdir(parents=True, exist_ok=True)
        output_path = (SANDBOX / filename).resolve()
        prs.save(str(output_path))
        return f"Created presentation: {filename} ({len(slides_data) + 1} slides)"

    return ToolHandler(
        definition=ToolDefinition(
            function={
                "name": "create_presentation",
                "description": (
                    "Create a PowerPoint (.pptx) presentation with smart layout detection."
                    " Each slide auto-detects as bullets, code, two-column, or quiz based on content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Presentation title"},
                        "subtitle": {"type": "string", "description": "Optional subtitle"},
                        "filename": {"type": "string", "description": "Output filename (default: presentation.pptx)"},
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
                                            "Slide content items. Use # for sub-headings,"
                                            " > for quotes. Code detection is automatic."
                                        ),
                                    },
                                    "layout": {
                                        "type": "string",
                                        "description": "Optional: 'bullets', 'code', 'two_column', 'quiz'",
                                    },
                                },
                                "required": ["title"],
                            },
                            "description": "Array of slides. Each slide has title and content array.",
                        },
                    },
                    "required": ["title", "slides"],
                },
            },
        ),
        execute=_execute,
    )

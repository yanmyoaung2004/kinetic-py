# AI-Powered Presentation Design

## How Professional Tools Generate Beautiful Slides

Based on research of production-grade presentation tools (including the ppt-master skill system), here are the key principles and techniques for creating stunning PowerPoint decks with AI.

---

## 1. Design System First

Professional presentation tools don't just dump content on slides — they establish a **design system** first:

### Color Palette (4 colors)
```
Primary accent   → Headers, titles, highlights
Dark text        → Body content  
Light accent     → Subtitles, secondary text
Background       → Slide background
```

### Typography Hierarchy
```
Title slide      → 44pt bold
Slide title      → 28pt bold
Body text        → 18pt regular
Code             → 13pt monospace
Subtitle/quote   → 14pt italic
```

### Spacing Grid
```
Margins          → 0.5 inches on all sides
Title bar        → 1.0 inches tall
Content area     → remaining space
Between items    → 6pt spacing
```

**Why it works:** A consistent design system makes slides look intentional and professional, even when content varies. The human eye picks up on consistency instantly.

---

## 2. Smart Layout Detection

Don't ask users to specify layouts — **detect from content**:

| Content Pattern | Best Layout | Example Input |
|----------------|-------------|---------------|
| Short single line | Center text | "Thank you" |
| Question marks + answers | Quiz | "?What is AI?" / "AI is..." |
| Code keywords (def, import, ```) | Code block | Code snippets |
| Long paragraphs or many items | Two columns | 8+ bullet points |
| Everything else | Bullets / list | Standard content |

**Why it works:** Users think about content, not layout. Auto-detection removes cognitive load while making better layout choices than most users would.

---

## 3. Visual Style Presets

Offer 4-5 distinct visual moods that users can choose from:

| Style | Accent | Vibe | Best For |
|-------|--------|------|----------|
| **Corporate** | Blue (#1A73E8) | Professional, safe | Business meetings, stakeholders |
| **Dark Tech** | Cyan (#00CCFF) | Modern, futuristic | Tech demos, developer talks |
| **Minimal** | Charcoal (#333) | Clean, elegant | Executive summaries, design reviews |
| **Warm** | Orange (#E86C00) | Friendly, approachable | Education, workshops |
| **Nature** | Green (#2E7D32) | Calm, organic | Sustainability, healthcare |

**Why it works:** Color psychology is real. A dark blue slide feels different from a warm orange one, even with identical content. Giving users a choice of mood without requiring design expertise.

---

## 4. Professional Title Slides

The title slide sets the entire tone. Professional tools always include:

```
┌─────────────────────────────────────┐
│                                     │
│           Presentation Title        │  ← 44pt bold
│                                     │
│           Optional Subtitle         │  ← 22pt light
│                                     │
│                                     │
│           March 15, 2026            │  ← 14pt light
│                                     │
│─────────────────────────────────────│  ← Decorative bar
└─────────────────────────────────────┘
```

**Elements:** Title, subtitle, date, decorative accent bar. No clutter.

---

## 5. Content Slide Architecture

Every content slide follows the same structure:

```
┌─── ACCENT BAR ─────────────────────┐  ← Slide title (28pt bold)
│                                     │
│  • Bullet point one                │  ← Body (18pt)
│  • Bullet point two                │
│  • Bullet point three              │  ← 6pt spacing
│                                     │
└─────────────────────────────────────┘
```

**The accent bar** is critical — it visually anchors the slide and ties it back to the title slide through shared color.

---

## 6. Speaker Notes

Professional decks include speaker notes for every slide. Notes are:
- Written in natural language (as if speaking)
- Include key talking points
- Remind the presenter of context
- Embedded in the PPTX `<p:notes>` element

```xml
<p:notes>
  <p:sp>
    <p:nvSpPr>...</p:nvSpPr>
    <p:spPr/>
    <p:txBody>
      <a:p>
        <a:r><a:t>Walk through the architecture diagram here</a:t></a:r>
      </a:p>
    </p:txBody>
  </p:sp>
</p:notes>
```

---

## 7. Slide Transitions

Subtle transitions make decks feel polished:

| Transition | Effect | When to Use |
|-----------|--------|-------------|
| Fade | Crossfade | General purpose |
| Push | Slides push each other | Narrative flow |
| Wipe | Bar wipes across | Section changes |
| Dissolve | Particles dissolve | Creative talks |

Best practice: use **one transition** for the entire deck. Mixing transitions looks amateurish.

---

## 8. Content Formatting Rules

### Bullet Points
- Start with a bullet (• or —)
- Keep each line under 80 characters
- Use parallel structure (same verb tense)
- Maximum 6-7 bullets per slide
- Sub-headings marked with `#` prefix

### Code Blocks
- Use monospace font (Consolas)
- Light gray background (#F0F0F0)
- Smaller font size (13pt)
- No syntax highlighting needed for PPTX

### Quotes
- Italic text
- Muted color (gray or light accent)
- Smaller font size (14pt)
- Surround with `>` prefix in input

### Two-Column Layouts
- Split content evenly (first half left, second half right)
- Equal column widths
- Works well for lists, comparisons, timelines
- Auto-triggered when content has 6+ items or long lines

---

## 9. Common Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Fix |
|-------------|--------------|-----|
| Too many bullets | Audience can't read fast enough | Split into multiple slides |
| Tiny text (<14pt) | Unreadable in large rooms | Use 18pt minimum for body |
| Mixed fonts | Looks unprofessional | One font family throughout |
| No color hierarchy | Everything blends together | Use accent color for headers |
| Inconsistent spacing | Looks sloppy | Use a grid (0.5in margins) |
| No speaker notes | Presenter forgets context | Always add notes |

---

## 10. The PPT-Master Pipeline (Reference)

The most advanced presentation generator (ppt-master) uses this pipeline:

```
Source (PDF/DOCX/URL/Text)
       ↓
[Project Init] → Creates directory structure
       ↓
[Strategist AI] → Designs spec (colors, fonts, layout, images)
       ↓
[Eight Confirmations] → User approves each design decision
       ↓
[Image Acquisition] → AI generates + web searches images
       ↓
[Executor AI] → Generates SVG slides one by one
       ↓
[Quality Check] → Validates SVG against standards
       ↓
[Post-Processing] → Embeds icons, crops images, flattens text
       ↓
[PPTX Export] → Converts SVG → native DrawingML shapes
       ↓
[Narration] → Optional TTS audio embedding
       ↓
Output: Native .pptx (fully editable in PowerPoint)
```

Our `create_presentation` tool uses a **simplified but effective** version of this approach:
- Design spec → visual style presets (simpler, no SVG)
- Layout detection → content-aware auto-detection
- Quality → consistent design system
- Notes → embedded per-slide speaker notes
- Export → native python-pptx with proper DrawingML

---

## 11. Testing Your Presentations

```
1. Open the .pptx in PowerPoint / Google Slides
2. Check that:
   - Title slide has proper spacing
   - All slides have consistent accent colors
   - Bullets are aligned and readable
   - Code blocks use monospace font
   - Speaker notes are present (View → Notes)
   - Transitions flow smoothly
```

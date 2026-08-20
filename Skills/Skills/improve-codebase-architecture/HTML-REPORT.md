# HTML report format

The architectural review is one self-contained static HTML document published
privately through Slate. The local temp file is upload staging, not the
delivery surface. Use inline CSS, HTML, and inline SVG. Slate blocks JavaScript,
forms, iframes, and local filesystem links.

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Architecture review: {{repo name}}</title>
    <style>
      :root {
        color-scheme: light;
        --paper: #f8f7f4;
        --ink: #172033;
        --muted: #667085;
        --line: #d9dde5;
        --accent: #087f5b;
        --leak: #c92a2a;
        --warning: #9a6700;
      }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--paper); color: var(--ink); font: 16px/1.5 ui-sans-serif, system-ui, sans-serif; }
      main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }
      header, article, .top-pick { background: white; border: 1px solid var(--line); border-radius: 16px; padding: 24px; }
      #candidates { display: grid; gap: 24px; margin: 24px 0; }
      .diagrams { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
      .diagram { min-height: 300px; border: 1px solid var(--line); border-radius: 12px; padding: 16px; }
      .badges { display: flex; flex-wrap: wrap; gap: 8px; }
      .badge { border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; }
      .strong { background: #d3f9d8; color: #176b38; }
      .explore { background: #fff3bf; color: #7c5400; }
      .speculative { background: #e9ecef; color: #495057; }
      .files { font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); }
      .seam { stroke-dasharray: 4 4; }
      .leak { stroke: var(--leak); }
      .deep { fill: #172033; color: white; }
      @media (max-width: 760px) { .diagrams { grid-template-columns: 1fr; } }
    </style>
  </head>
  <body>
    <main>
      <header>...</header>
      <section id="candidates">...</section>
      <section id="top-recommendation" class="top-pick">...</section>
    </main>
  </body>
</html>
```

## Header

Repo name, date, and a compact legend: solid box = module, dashed line = seam, red arrow = leakage, thick dark box = deep module. No introduction paragraph — straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse, plain, and uses the glossary terms (from the `/codebase-design` skill) without ceremony.

Each candidate is one `<article>`:

- **Title** — short, names the deepening (e.g. "Collapse the Order intake pipeline").
- **Badge row** — recommendation strength (`Strong` = emerald, `Worth exploring` = amber, `Speculative` = slate), plus a tag for the dependency category (`in-process`, `local-substitutable`, `ports & adapters`, `mock`).
- **Files** — monospaced list using the `.files` class.
- **Before / After diagram** — the centrepiece. Two columns, side by side. See patterns below.
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each. e.g. "Tests hit one interface", "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (if applicable) — one line in an amber-tinted box.

No paragraphs of explanation. If the diagram needs a paragraph to be understood, redraw the diagram.

## Diagram patterns

Pick the pattern that fits the candidate. Mix them. Don't make every diagram look the same — variety is part of the point.

### Static dependency or call-flow graph

Use inline SVG when the point is "X calls Y calls Z." Draw module boxes with
`<rect>`, labels with `<text>`, and calls or leakage with `<path>` markers.
Provide an accessible text summary next to each SVG. A before and after pair can
show six calls collapsing into one interface without runtime rendering.

```html
<div class="diagram">
  <svg viewBox="0 0 520 260" role="img" aria-labelledby="before-title before-desc">
    <title id="before-title">Order intake before deepening</title>
    <desc id="before-desc">Three shallow modules call each other and pricing leaks across the seam.</desc>
    <rect x="20" y="80" width="130" height="64" rx="8" fill="#fff" stroke="#667085" />
    <text x="85" y="116" text-anchor="middle">OrderHandler</text>
    <!-- Add the remaining boxes and paths explicitly. -->
  </svg>
</div>
```

### Hand-built boxes and arrows

Modules can be `<div>` elements with borders and labels. Draw arrows with inline
SVG `<line>` or `<path>` elements. Use this when the after diagram needs one
thick-bordered deep module with faded internals.

### Cross-section (good for layered shallowness)

Stack horizontal bands with fixed heights and a strong left border in the
inline stylesheet. Before: 6 thin layers each doing nothing. After: 1 thick
band labelled with the consolidated responsibility.

### Mass diagram (good for "interface as wide as implementation")

Two rectangles per module — one for interface surface area, one for implementation. Before: interface rectangle is nearly as tall as the implementation rectangle (shallow). After: interface rectangle is short, implementation rectangle is tall (deep).

### Call-graph collapse

Before: a tree of function calls rendered as nested boxes. After: the same tree collapsed into one box, with the now-internal calls shown faded inside it.

## Style guidance

- Lean editorial, not corporate-dashboard. Use generous whitespace. A serif font stack is optional for headings.
- Colour sparingly: one accent (emerald or indigo) plus red for leakage and amber for warnings.
- Keep diagrams ~320px tall so before/after sits comfortably side by side without scrolling.
- Style module labels as small uppercase text with wide letter spacing. They should read as schematic, not as interface copy.
- Include no scripts. Every diagram must be fully rendered in the uploaded bytes.

## Top recommendation section

One larger card. Candidate name, one sentence on why, anchor link to its card. That's it.

## Tone

Plain English, concise — but the architectural nouns and verbs come straight from the `/codebase-design` skill. Concision is not an excuse to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API, signature (for interface) · boundary (for seam) · layer, wrapper (for module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: *"locality: bugs concentrate in one module"*, *"leverage: one interface, N call sites"*, *"interface shrinks; implementation absorbs the wrappers"*. Don't write *"easier to maintain"* or *"cleaner code"* — those terms aren't in the glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. If a term isn't in the `/codebase-design` glossary, reach for one that is before inventing a new one.

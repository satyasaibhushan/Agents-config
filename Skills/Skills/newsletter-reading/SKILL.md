---
name: newsletter-reading
description: Pick and teach articles from the user's tech newsletters. Use when the user asks to read, go through, catch up on, or learn from a newsletter or newsletter issue.
---

# Newsletter reading

Select by value, not arrival order.

1. Skim every article in the issues first. Teach nothing yet.
2. Keep what changes how the user builds: application-level engineering
   decisions, architecture trade-offs, failure modes. Drop what he already
   knows or that only restates old news.
3. Skip local model hosting, GPU tuning, quantization, and other inference
   optimization unless he asks for them.
4. Merge articles that cover the same idea into one topic; cite each source.
5. List the shortlist with one line on why each matters, then teach the top
   topic.

Teaching, in chat:

- When relationships or ownership are central (who calls whom, who owns which
  state), open with a compact inline flowchart (Mermaid or ASCII), then prose
  or code.
- After each concept, ask which parts are already familiar before advancing.

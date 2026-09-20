---
name: goodnotes-note-generator
description: >-
  Turn source material into realistic Goodnotes-style handwritten note images: portrait 3:4 iPad pages,
  pure white background, mixed Chinese and English handwriting, hand-drawn arrows and doodles, medium-light
  density, for sharing on Xiaohongshu-style platforms. Triggers: 笔记图、手写笔记图、Goodnotes 风格、小红书笔记图、
  把资料做成笔记图、concept notes, visual summaries, exam notes, paper takeaways, slide decks, screenshots, PDFs,
  raw text. Also covers the web chat handoff for when the images must be generated in a browser-based chat
  that cannot read local files: 网页端出图、传给 ChatGPT 出图、网页端读不了本地文件、把本地资料发给网页版画笔记图、
  网页版看不到我的文件、打包给网页端出图. It builds an upload bundle (page images, upload manifest, paste-ready
  prompt, optional context pack) so the web chat only has to render the pages; palette #005087, #86B8CE,
  #B23939, #D88080.
---

Use this skill to transform source material into a small set of realistic Goodnotes-style note images.

## Default operating mode
- Accept text, PDFs, papers, screenshots, lecture notes, slide decks, or mixed source material.
- Assume the desired output is image-first, not long prose.
- Default to 4 pages unless the user specifies a different count or the material clearly requires fewer or more pages.
- Use a portrait iPad page with aspect ratio 3:4.
- Keep a pure white page background.
- Optimize for social sharing: each page must be scannable, visually interesting, and not overcrowded.

## Ask only when necessary
Ask at most 2 short clarifying questions only if a missing detail would materially reduce quality. Good examples:
- Which sections of a long paper should be prioritized?
- How many pages are desired?
- Should the notes be mostly Chinese, mostly English, or mixed?

If the user already provided enough detail, do not delay. Proceed directly.

## Workflow
1. Read and extract the source content.
2. Identify the core teaching goal and the 3–6 most important subtopics.
3. Chunk the material into page-sized units. Use one main idea per page.
4. Select the best page pattern for each page. See `references/output-patterns.md`.
5. Compress the wording. Prefer note fragments, keywords, labels, arrows, and small callouts over long paragraphs.
6. Generate the images in a consistent Goodnotes-style visual system. See `references/visual-style.md`.

## Page planning rules
- Keep one page focused on one clear theme.
- Aim for 1 main title, 2–4 sub-sections, and concise supporting notes.
- Keep strong whitespace. Do not try to “use every corner.”
- If the source material is dense, split it across more pages instead of shrinking everything.
- If a page starts to feel text-heavy, replace some text with a small hand-drawn diagram, flow, comparison, icon, or mini chart.
- Preserve the most important English terminology exactly when needed, even inside mostly Chinese notes.
- When the source contains formulas, structures, or processes, visualize them rather than restating them as dense prose.

## Visual requirements
Follow `references/visual-style.md`.

Key requirements:
- Render the page like a realistic handwritten Goodnotes note, not a polished poster.
- Use realistic mixed Chinese and English handwriting. Chinese should look neat, natural, and slightly varied. English should look like tidy handwritten print, not a generic system font.
- Keep the page pure white.
- Use black or dark gray for most text.
- Use the palette colors sparingly for headings, highlights, underlines, labels, and emphasis:
  - `#005087`
  - `#86B8CE`
  - `#B23939`
  - `#D88080`
- Draw arrows, underlines, brackets, doodles, and small illustrations in a hand-drawn style.
- Make simple diagrams look sketched by hand and educational.
- Avoid glossy poster effects, perfect vector geometry, or dense infographic layouts.

## Realism rules
- Favor authenticity over perfection.
- Keep linework slightly irregular but still clean.
- Allow subtle size variation, spacing variation, and mild baseline wobble in handwriting.
- Keep everything legible. “Realistic” must never mean messy.
- Do not overuse stickers or decorative elements.
- Avoid filling the page edge to edge.

## Content writing rules
- Be concise.
- Prefer phrases over sentences.
- Convert long explanations into:
  - bullets
  - numbered steps
  - short comparisons
  - arrows and cause-effect chains
  - mini summaries
- Use bilingual layout only where helpful. If the source is Chinese, keep Chinese dominant and preserve important English terms. If the source is English, keep English dominant and optionally add short Chinese glosses when useful.
- When text fidelity matters, explicitly specify exact text to render.

## Output behavior
- If the user asks for images directly, generate them.
- If the user asks first for content organization, provide a concise page plan and then offer or proceed to generate the images depending on the request.
- When the user gives a long document, summarize only what is essential for the chosen page set.
- If the user says “make it more like Goodnotes,” increase handwritten realism, spacing, and hand-drawn annotations rather than adding more decoration.
- If the user says “one page looks boring,” reduce text density and add a small sketch, relationship diagram, or highlighted structure.

## Web chat mode（网页端模式）
Use this mode when the images will be generated somewhere that cannot read local paths, such as ChatGPT in a browser. Triggers: the user says they will use the web chat to generate the images, that the web version cannot access local files, or asks to package local material for a browser AI.

The division of labor is fixed: **this side owns content and specification; the web chat only renders the pages.**

Workflow:
1. Read the source material and do the page plan here (same rules as the normal workflow: one theme per page, default 4-page set, patterns from `references/output-patterns.md`).
2. Render upload-ready material with the bundled script:
   `python3 scripts/render_upload_pages.py <sources...> [--out DIR] [--max-files 5] [--max-mb 5] [--long-edge 2000]`
   It writes `pages/` (PNG page images, JPEG only when a page exceeds the size budget), `context_pack.md`, `upload_manifest.md`, and `handoff.json`, and never overwrites an existing non-empty output directory.
3. Write `web_prompt.md` yourself — never a blank template — following the seven-part structure in `references/web-handoff.md`: role and evidence boundary, image goal, per-page plan, visual system, the exact text to render per page, prohibitions, output requirements. Lock the per-page wording here so the web chat never rewrites content.
4. Hand over the manifest and the prompt together, and state which files must be uploaded.

Rules:
- Never put local absolute paths in the web prompt. Refer only to uploaded filenames.
- Uploaded page images are source material for reading, not layouts to copy. Say so explicitly in the prompt when images are supplied.
- Keep the default budget (≤ 5 files, ≤ 5 MB each, long edge ≤ 2000 px) unless the user gives a different cap; degrade gracefully and record anything left out.
- Do not upload secrets, credentials, personal data, or restricted material. Reuse the safety, context-pack, and manifest conventions from the `web-ai-handoff` skill instead of restating them.
- Read `references/web-handoff.md` for the bundle layout, budget degradation order, quality checklist, and failure fixes.

## Quality checklist
Before finalizing, verify all of the following:
- The page looks like a real handwritten digital note.
- The layout is portrait 3:4 and social-media friendly.
- No single page is overcrowded.
- The page is still interesting despite low density.
- Chinese and English text both look intentional and readable.
- Hand-drawn arrows and mini illustrations feel consistent.
- The white background remains clean.
- The palette is used consistently but lightly.
- The set feels coherent across pages.

## Resource files
- Use `references/visual-style.md` for the visual system and realism cues.
- Use `references/output-patterns.md` to choose page archetypes and structure content efficiently.
- Use `references/web-handoff.md` when the images are generated in a browser-based chat; it defines the handoff bundle, the paste-ready prompt structure, and the upload budget.
- Use `scripts/render_upload_pages.py` to render local sources into upload-ready page images plus an upload manifest.

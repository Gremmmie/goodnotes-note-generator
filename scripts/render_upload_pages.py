#!/usr/bin/env python3
"""Render local source material into an upload bundle for a web chat AI.

A browser-based chat cannot read local paths. This script turns local sources
(PDF / images / text) into upload-ready PNG page images, a text context pack,
and an upload manifest, so the web chat only has to render note pages.

Outputs inside the target directory:
    pages/            upload-ready PNG page images (3:4-agnostic, source pages)
    context_pack.md   labeled text excerpts extracted from text sources / PDFs
    upload_manifest.md
    handoff.json      machine-readable summary for the calling agent

Dependencies: pdftoppm + pdftotext (Poppler), Pillow, optional sips fallback.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - dependency guard
    raise SystemExit("error: Pillow is required (python3 -m pip install pillow)") from None

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".heif"}
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".tex", ".rst"}
PDF_EXT = {".pdf"}

DEFAULT_MAX_FILES = 5
DEFAULT_MAX_MB = 5.0
DEFAULT_LONG_EDGE = 2000
MIN_LONG_EDGE = 1000
DOWNSCALE_STEPS = (1.0, 0.85, 0.72, 0.6)
JPEG_DOWNSCALE_STEPS = (1.0, 0.8, 0.62, 0.5)
JPEG_QUALITY_STEPS = (88, 78, 68, 55)
CONTEXT_PACK_CHAR_BUDGET = 120_000


class HandoffError(RuntimeError):
    pass


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def slugify(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ch in " .":
            keep.append("_")
    slug = "".join(keep).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:48] or "source"


def unique_slug(name: str, taken: set[str]) -> str:
    """Return a slug that no other source in this run has claimed.

    Two sources can share a stem (paper.pdf and paper.png, or same-named files
    from different folders); without this they would overwrite each other.
    """
    base = slugify(name)
    slug = base
    index = 2
    while slug in taken:
        slug = f"{base}-{index}"
        index += 1
    taken.add(slug)
    return slug


def safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def size_label(size: int | None) -> str:
    return human_size(size) if size is not None else "—（源文件已不可读）"


def require_tool(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise HandoffError(
            f"'{tool}' not found. Install Poppler first (macOS: brew install poppler)."
        )
    return path


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if len(detail) > 600:
            detail = detail[:600] + " …（已截断）"
        raise HandoffError(f"command failed ({Path(cmd[0]).name}, exit {result.returncode}): {detail}")


def resolve_out_dir(base: Path, requested: Path | None, force: bool) -> Path:
    out = (requested or (base / "web_handoff")).expanduser().resolve()
    if out.exists() and not out.is_dir():
        raise HandoffError(f"--out must be a directory, but this path is a file: {out}")
    if force or not out.exists() or not any(out.iterdir()):
        return out
    index = 2
    while True:
        candidate = out.with_name(f"{out.name}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def write_jpeg(image, path: Path, quality: int) -> None:
    try:
        image.save(path, format="JPEG", quality=quality, optimize=True)
        return
    except Exception:
        sips = shutil.which("sips")
        if not sips:
            raise
    temp_png = path.with_suffix(".tmp.png")
    image.save(temp_png, format="PNG")
    run(
        [
            sips,
            "-s",
            "format",
            "jpeg",
            "-s",
            "formatOptions",
            str(quality),
            str(temp_png),
            "--out",
            str(path),
        ]
    )
    temp_png.unlink(missing_ok=True)


def scaled(image, long_edge: int, factor: float):
    # Never let the soft floor override a deliberately smaller --long-edge.
    floor = min(MIN_LONG_EDGE, long_edge)
    edge = max(floor, int(long_edge * factor))
    candidate = image.copy()
    if max(candidate.size) > edge:
        candidate.thumbnail((edge, edge), Image.LANCZOS)
    return candidate


def save_png(image, dest: Path, long_edge: int, max_bytes: int) -> dict:
    Image.init()  # plugin registry is lazy; JPEG/PNG writers may be missing otherwise
    working = image.copy()
    if working.mode not in ("RGB", "L"):
        working = working.convert("RGB")
    info = {
        "path": dest,
        "width": None,
        "height": None,
        "bytes": 0,
        "format": "PNG",
        "over_budget": False,
    }

    for factor in DOWNSCALE_STEPS:
        candidate = scaled(working, long_edge, factor)
        candidate.save(dest, format="PNG", optimize=True)
        size = dest.stat().st_size
        info.update(width=candidate.width, height=candidate.height, bytes=size)
        if size <= max_bytes:
            return info

    # PNG cannot meet the budget (screenshots of dense slides or noisy scans):
    # escalate to JPEG and keep tightening until it fits.
    jpeg_path = dest.with_suffix(".jpg")
    best: tuple[int, tuple[int, int]] | None = None
    chosen: tuple[float, int] | None = None
    for factor in JPEG_DOWNSCALE_STEPS:
        candidate = scaled(working, long_edge, factor)
        for quality in JPEG_QUALITY_STEPS:
            write_jpeg(candidate, jpeg_path, quality)
            size = jpeg_path.stat().st_size
            if best is None or size < best[0]:
                best = (size, candidate.size)
            if size <= max_bytes:
                chosen = (factor, quality)
                break
        if chosen:
            break

    if best is None:
        return info
    size, (width, height) = best
    if size >= dest.stat().st_size:
        jpeg_path.unlink(missing_ok=True)
        return info
    if chosen:
        size = jpeg_path.stat().st_size
    dest.unlink(missing_ok=True)
    info.update(
        path=jpeg_path,
        width=width,
        height=height,
        bytes=size,
        format="JPEG",
        over_budget=size > max_bytes,
    )
    return info


def pdf_page_count(src: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    result = subprocess.run([pdfinfo, str(src)], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def render_pdf(
    src: Path,
    pages_dir: Path,
    slug: str,
    long_edge: int,
    max_bytes: int,
    max_pages: int,
) -> tuple[list[dict], str, int]:
    pdftoppm = require_tool("pdftoppm")
    pages_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".tmp_", dir=pages_dir))

    entries: list[dict] = []
    try:
        prefix = work_dir / "page"
        run(
            [
                pdftoppm,
                "-png",
                "-scale-to",
                str(long_edge),
                "-l",
                str(max_pages),
                str(src),
                str(prefix),
            ]
        )

        rendered = sorted(work_dir.glob("page*.png"))
        if not rendered:
            raise HandoffError(f"pdftoppm produced no pages for {src}")

        for index, raw in enumerate(rendered, start=1):
            dest = pages_dir / f"{slug}-p{index:02d}.png"
            with Image.open(raw) as image:
                info = save_png(image, dest, long_edge, max_bytes)
            info.update(
                page=index,
                source=src,
                upload_name=info["path"].name,
                purpose=f"{src.name} 第 {index} 页原页图（供网页端读图后据此出笔记图）",
                priority=1,
                tier="must",
                preparation="无需处理，作为图片直接上传",
            )
            entries.append(info)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    total_pages = pdf_page_count(src)
    omitted = max(0, total_pages - len(entries)) if total_pages else 0
    return entries, pdf_text(src), omitted


def normalize_image(
    src: Path, pages_dir: Path, slug: str, long_edge: int, max_bytes: int
) -> dict:
    pages_dir.mkdir(parents=True, exist_ok=True)
    dest = pages_dir / f"{slug}.png"
    try:
        with Image.open(src) as image:
            info = save_png(image, dest, long_edge, max_bytes)
    except Exception:
        sips = shutil.which("sips")
        if not sips:
            raise
        run([sips, "-s", "format", "png", str(src), "--out", str(dest)])
        with Image.open(dest) as image:
            info = save_png(image, dest, long_edge, max_bytes)
    info.update(
        page=1,
        source=src,
        upload_name=info["path"].name,
        purpose=f"{src.name} 原图（供网页端读图后据此出笔记图）",
        priority=1,
        tier="must",
        preparation="无需处理，作为图片直接上传",
    )
    return info


def pdf_text(src: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""
    result = subprocess.run(
        [pdftotext, "-layout", str(src), "-"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def read_text_source(src: Path) -> str:
    try:
        return src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HandoffError(f"cannot read {src}: {exc}") from exc


def build_context_pack(blocks: list[tuple[Path, str]]) -> tuple[str, bool]:
    lines: list[str] = [
        "# Context Pack",
        "",
        "本地文本摘录，供网页端在没有原文件的情况下理解源资料。",
        "每段标注来源文件名与页码；被省略的部分会显式标注。",
        "出于隐私考虑，本文件不含本地绝对路径，可直接上传。",
        "",
    ]
    used = 0
    truncated = False
    for source_index, (src, text) in enumerate(blocks, start=1):
        if not text.strip():
            continue
        stripped = text.strip()
        if used >= CONTEXT_PACK_CHAR_BUDGET:
            truncated = True
            lines += [f"## [来源 {source_index}] {src.name}", "", "（已达文本预算，本文件内容省略）", ""]
            continue
        remaining = CONTEXT_PACK_CHAR_BUDGET - used
        if len(stripped) > remaining:
            stripped = stripped[:remaining]
            truncated = True
            note = f"（此段已按 {CONTEXT_PACK_CHAR_BUDGET} 字符总预算截断）"
        else:
            note = ""
        used += len(stripped)
        lines += [f"## [来源 {source_index}] {src.name}", f"来源文件：`{src.name}`", ""]
        for page_number, page_text in enumerate(stripped.split("\f"), start=1):
            body = page_text.strip()
            if not body:
                continue
            lines += [f"### 第 {page_number} 页", "", "```", body, "```", ""]
        if note:
            lines += [note, ""]
    return "\n".join(lines).rstrip() + "\n", truncated


def manifest_table(
    entries: list[dict],
    sources: list[Path],
    budget_files: int,
    max_mb: float,
    context_pack: Path | None = None,
) -> str:
    rows = [
        "# Upload Manifest",
        "",
        f"生成时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        f"上传预算：≤ {budget_files} 个文件，单文件 ≤ {max_mb:g} MB",
        f"本包必须上传：{sum(1 for entry in entries if entry['tier'] == 'must')} 个文件",
        "",
        "> 隐私提示：本清单与 `handoff.json` **含本地绝对路径**，仅供本地使用，不要上传给网页端；",
        "> 需要上传的只有 `pages/` 里的页面图与（可选的）`context_pack.md`。",
        "",
        "| Priority | Upload filename | Local path | Size | Purpose | Preparation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        rows.append(
            "| {priority} ({tier}) | `{name}` | `{path}` | {size} | {purpose} | {prep} |".format(
                priority=entry["priority"],
                tier=entry["tier"],
                name=entry["upload_name"],
                path=entry["path"],
                size=human_size(entry["bytes"]) + ("（超预算）" if entry.get("over_budget") else ""),
                purpose=entry.get("purpose", ""),
                prep=entry.get("preparation", "无需处理"),
            )
        )
    if any(entry.get("over_budget") for entry in entries):
        rows.append("")
        rows.append(
            "> 警告：以上标（超预算）的页面图即使降到最低质量仍超过单文件上限。"
            "请降低 `--long-edge` 或 `--max-mb` 重跑，或按 `references/web-handoff.md` 的降级顺序拆分交付。"
        )
    for src in sources:
        if src.suffix.lower() in IMAGE_EXT:
            purpose = "源图原文件，仅在网页端需要更高分辨率时上传"
        else:
            purpose = "源文件全文，仅在网页端需要核对原文时上传"
        rows.append(
            f"| 5 (optional) | `{src.name}` | `{src}` | {size_label(safe_size(src))} | "
            f"{purpose} | 确认不含敏感信息 |"
        )
    if context_pack is not None:
        rows.append(
            f"| 2 (optional) | `{context_pack.name}` | `{context_pack}` | "
            f"{size_label(safe_size(context_pack))} | "
            "文本摘录，网页端无法读图或只接受文本时用它替代页面图（不含本地绝对路径） | 无需处理 |"
        )
    rows += [
        "| — (do not upload) | — | `.env`、密钥、凭据、未公开数据、含个人信息的附件 | — | "
        "安全边界 | 剔除，或用脱敏替代文本 |",
        "| — (do not upload) | `upload_manifest.md`、`handoff.json` | 含本地绝对路径 | — | "
        "隐私边界 | 仅本地使用，不要上传 |",
        "",
        "`must` = 必须上传；`optional` = 按需；`do not upload` = 明确禁止。",
        "",
    ]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render local sources into an upload bundle for a web chat AI."
    )
    parser.add_argument("sources", nargs="+", type=Path, help="PDF / image / text files")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    parser.add_argument("--long-edge", type=int, default=DEFAULT_LONG_EDGE)
    parser.add_argument(
        "--force",
        action="store_true",
        help="reuse the output directory even if it exists (may overwrite existing page images)",
    )
    args = parser.parse_args(argv)

    for flag, value, minimum in (
        ("--max-files", args.max_files, 1),
        ("--long-edge", args.long_edge, 200),
    ):
        if value < minimum:
            print(f"error: {flag} must be >= {minimum} (got {value})", file=sys.stderr)
            return 2
    if args.max_mb <= 0:
        print(f"error: --max-mb must be > 0 (got {args.max_mb:g})", file=sys.stderr)
        return 2

    sources = [path.expanduser().resolve() for path in args.sources]
    for src in sources:
        if not src.exists():
            print(f"error: source not found: {src}", file=sys.stderr)
            return 2

    max_bytes = int(args.max_mb * 1024 * 1024)
    try:
        out_dir = resolve_out_dir(sources[0].parent, args.out, args.force)
        out_dir.mkdir(parents=True, exist_ok=True)
        # pages/ is created lazily: a text-only run must not leave an empty directory.
        pages_dir = out_dir / "pages"

        entries: list[dict] = []
        text_blocks: list[tuple[Path, str]] = []
        skipped: list[tuple[Path, str]] = []
        remaining = args.max_files
        taken_slugs: set[str] = set()

        for src in sources:
            suffix = src.suffix.lower()
            try:
                if suffix in PDF_EXT:
                    if remaining <= 0:
                        skipped.append((src, f"超出 {args.max_files} 个上传文件预算，未纳入本包"))
                        continue
                    slug = unique_slug(src.stem, taken_slugs)
                    pdf_entries, text, omitted = render_pdf(
                        src, pages_dir, slug, args.long_edge, max_bytes, remaining
                    )
                    entries.extend(pdf_entries)
                    remaining -= len(pdf_entries)
                    if omitted:
                        skipped.append(
                            (
                                src,
                                f"源 PDF 共 {len(pdf_entries) + omitted} 页，"
                                f"按上传预算仅纳入前 {len(pdf_entries)} 页，其余 {omitted} 页未纳入本包",
                            )
                        )
                    if text.strip():
                        text_blocks.append((src, text))
                elif suffix in IMAGE_EXT:
                    if remaining <= 0:
                        skipped.append((src, f"超出 {args.max_files} 个上传文件预算，未纳入本包"))
                        continue
                    slug = unique_slug(src.stem, taken_slugs)
                    entries.append(
                        normalize_image(src, pages_dir, slug, args.long_edge, max_bytes)
                    )
                    remaining -= 1
                elif suffix in TEXT_EXT:
                    # 文本源不占用图片上传预算，它们进入 context_pack.md
                    text_blocks.append((src, read_text_source(src)))
                else:
                    skipped.append((src, f"不支持的扩展名 '{suffix or 'none'}'"))
            except Exception as exc:  # 单个源失败不拖垮整批，记录后继续
                skipped.append((src, f"处理失败（{type(exc).__name__}）：{exc}"))

        if len(entries) > args.max_files:
            for entry in entries[args.max_files :]:
                skipped.append((entry["source"], f"超出 {args.max_files} 个上传文件预算，未纳入本包"))
                entry["path"].unlink(missing_ok=True)
            entries = entries[: args.max_files]

        context_pack_path = None
        truncated = False
        if text_blocks:
            content, truncated = build_context_pack(text_blocks)
            context_pack_path = out_dir / "context_pack.md"
            context_pack_path.write_text(content, encoding="utf-8")

        manifest_path = out_dir / "upload_manifest.md"
        manifest_path.write_text(
            manifest_table(
                entries, sources, args.max_files, args.max_mb, context_pack_path
            ),
            encoding="utf-8",
        )

        summary = {
            "out_dir": str(out_dir),
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "budget": {"max_files": args.max_files, "max_mb": args.max_mb, "long_edge": args.long_edge},
            "sources": [str(src) for src in sources],
            "pages": [
                {
                    "upload_name": entry["upload_name"],
                    "local_path": str(entry["path"]),
                    "bytes": entry["bytes"],
                    "width": entry["width"],
                    "height": entry["height"],
                    "format": entry["format"],
                    "over_budget": bool(entry.get("over_budget")),
                    "page": entry["page"],
                    "source": str(entry["source"]),
                    "tier": entry["tier"],
                }
                for entry in entries
            ],
            "over_budget_pages": [
                entry["upload_name"] for entry in entries if entry.get("over_budget")
            ],
            "context_pack": str(context_pack_path) if context_pack_path else None,
            "context_pack_truncated": truncated,
            "manifest": str(manifest_path),
            "skipped": [{"path": str(path), "reason": reason} for path, reason in skipped],
            "notes": [
                "upload_manifest.md 与 web_prompt.md 一起交给用户；web_prompt.md 由 agent 依据本清单和 context_pack 撰写。",
                "context_pack 是文本交接物，页面图包是图像交接物；网页端出图只需其一即可，除非每页文案需要逐字锁定。",
                "context_pack 为 null 时说明源材料没有可抽取的文本层（扫描件或纯栅格 PDF）：网页端只能靠上传的页面图读图，逐页文案必须由 agent 在本地完成压缩与锁定后写进 web_prompt.md。",
                "over_budget_pages 非空时，需按 references/web-handoff.md 的降级顺序处理（合并页面、降分辨率、只传关键页），并在交付说明里点明。",
                "upload_manifest.md 与 handoff.json 含本地绝对路径，仅供本地使用；不要上传给网页端。",
                "skipped 非空时要在交付说明里逐条交代原因（超预算、损坏文件、扩展名不支持等），不要静默丢弃。",
            ],
        }
        (out_dir / "handoff.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if skipped:
            print(
                f"warning: {len(skipped)} 个来源未纳入本包，原因见 handoff.json 的 skipped 字段",
                file=sys.stderr,
            )
        if not entries and not context_pack_path:
            print("warning: nothing uploadable was produced", file=sys.stderr)
            return 1
        return 0
    except (HandoffError, OSError) as exc:
        # OSError covers an unwritable --out, a vanished source, a full disk, …
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # 兜底：不以 traceback 形式把内部细节喷给使用者
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Regression tests for scripts/render_upload_pages.py.

Run:  python3 -m unittest discover -s tests -v

PDF cases are skipped automatically when Poppler (pdftoppm) is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "render_upload_pages.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from PIL import Image  # noqa: E402

import render_upload_pages as rup  # noqa: E402

HAS_POPPLER = shutil.which("pdftoppm") is not None


def write_raster_pdf(path: Path, pages: int = 2, size: tuple[int, int] = (600, 800)) -> None:
    Image.init()
    images = []
    for index in range(pages):
        image = Image.new("RGB", size, "white")
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:], resolution=150)


def write_text_pdf(path: Path, page_texts: list[str]) -> None:
    """Minimal text-layer PDF so pdftotext extraction can be tested."""
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(len(page_texts)))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode()
    for index, text in enumerate(page_texts):
        page_num, content_num = 4 + index * 2, 5 + index * 2
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode()
        stream = f"BT /F1 12 Tf 60 780 Td ({text}) Tj ET".encode()
        objects[content_num] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    buffer = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(buffer)
        buffer += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_position = len(buffer)
    size = max(objects) + 1
    buffer += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, size):
        buffer += f"{offsets.get(number, 0):010d} 00000 n \n".encode()
    buffer += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_position}\n%%EOF\n".encode()
    )
    path.write_bytes(bytes(buffer))


class HandoffTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="goodnotes-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_script(self, *args: str, cwd: Path | None = None):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd or self.tmp),
        )
        summary = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
        return result, summary

    def png(self, name: str, size: tuple[int, int] = (300, 400), mode: str = "RGB") -> Path:
        path = self.tmp / name
        Image.init()
        Image.new(mode, size, "white").save(path)
        return path

    # --- unit level -----------------------------------------------------

    def test_slugify_keeps_cjk_and_strips_separators(self) -> None:
        # callers pass a stem, so a dot inside the name simply becomes a separator
        self.assertEqual(rup.slugify("IRES 活性 预测"), "IRES_活性_预测")
        self.assertEqual(rup.slugify("IRES 活性 预测.pdf"), "IRES_活性_预测_pdf")
        self.assertEqual(rup.slugify("!!!"), "source")
        self.assertEqual(rup.slugify("a" * 80), "a" * 48)

    def test_unique_slug_disambiguates_same_stem(self) -> None:
        taken: set[str] = set()
        self.assertEqual(rup.unique_slug("paper", taken), "paper")
        self.assertEqual(rup.unique_slug("paper", taken), "paper-2")
        self.assertEqual(rup.unique_slug("paper", taken), "paper-3")

    def test_scaled_respects_small_explicit_long_edge(self) -> None:
        image = Image.new("RGB", (4000, 3000), "white")
        shrunk = rup.scaled(image, 800, 0.85)
        self.assertEqual(max(shrunk.size), 800)
        shrunk_default = rup.scaled(image, rup.DEFAULT_LONG_EDGE, 0.6)
        self.assertEqual(max(shrunk_default.size), 1200)
        self.assertGreaterEqual(max(shrunk_default.size), rup.MIN_LONG_EDGE)
        # the soft floor still stops the smallest steps from collapsing too far
        self.assertEqual(max(rup.scaled(image, rup.DEFAULT_LONG_EDGE, 0.2).size), rup.MIN_LONG_EDGE)

    def test_human_size_and_safe_size(self) -> None:
        self.assertEqual(rup.human_size(512), "512 B")
        self.assertEqual(rup.human_size(2048), "2.0 KB")
        self.assertIsNone(rup.safe_size(self.tmp / "missing.png"))
        self.assertIn("不可读", rup.size_label(None))

    def test_context_pack_carries_no_absolute_paths(self) -> None:
        content, _ = rup.build_context_pack([(self.tmp / "notes.md", "正文内容")])
        self.assertIn("notes.md", content)
        self.assertNotIn(str(self.tmp), content)

    # --- CLI level ------------------------------------------------------

    def test_no_arguments_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=str(self.tmp)
        )
        self.assertNotEqual(result.returncode, 0)

    def test_usage_error_is_not_treated_as_success(self) -> None:
        result, _ = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--max-files", result.stdout)

    def test_missing_source_exits_2(self) -> None:
        result, _ = self.run_script("nope.pdf")
        self.assertEqual(result.returncode, 2)

    def test_invalid_budgets_rejected(self) -> None:
        self.png("a.png")
        for args in (("--max-files", "0"), ("--max-mb", "0"), ("--long-edge", "100")):
            result, _ = self.run_script(*args, "a.png")
            self.assertEqual(result.returncode, 2, msg=str(args))

    def test_unsupported_extension_is_skipped_not_crashing(self) -> None:
        (self.tmp / "doc.docx").write_bytes(b"x")
        self.png("keep.png")
        result, summary = self.run_script("doc.docx", "keep.png")
        self.assertEqual(result.returncode, 0)
        self.assertEqual([page["upload_name"] for page in summary["pages"]], ["keep.png"])
        self.assertIn("不支持", summary["skipped"][0]["reason"])

    def test_text_only_run_creates_no_pages_dir(self) -> None:
        (self.tmp / "note.md").write_text("hello 内容", encoding="utf-8")
        result, summary = self.run_script("note.md")
        self.assertEqual(result.returncode, 0)
        self.assertFalse((Path(summary["out_dir"]) / "pages").exists())
        self.assertTrue(Path(summary["context_pack"]).exists())

    def test_output_dir_is_not_overwritten(self) -> None:
        self.png("a.png")
        _, first = self.run_script("a.png")
        _, second = self.run_script("a.png")
        self.assertNotEqual(first["out_dir"], second["out_dir"])
        self.assertTrue(second["out_dir"].endswith("_2"))

    def test_out_pointing_at_a_file_fails_cleanly(self) -> None:
        source = self.png("a.png")
        blocker = self.tmp / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        result, _ = self.run_script(str(source), "--out", str(blocker))
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be a directory", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_force_reuses_the_same_directory(self) -> None:
        self.png("a.png")
        _, first = self.run_script("a.png")
        _, second = self.run_script("a.png", "--force")
        self.assertEqual(first["out_dir"], second["out_dir"])

    def test_image_sources_get_distinct_names_and_none_overwrite(self) -> None:
        nested = self.tmp / "sub"
        nested.mkdir()
        self.png("paper.png")
        self.png("paper.webp")
        shutil.move(str(self.tmp / "paper.webp"), str(nested / "paper.webp"))
        result, summary = self.run_script("paper.png", "sub/paper.webp", "--out", "bundle")
        self.assertEqual(result.returncode, 0)
        names = [page["upload_name"] for page in summary["pages"]]
        self.assertEqual(len(names), len(set(names)), msg=str(names))
        for page in summary["pages"]:
            self.assertTrue(Path(page["local_path"]).exists())

    def test_source_larger_than_long_edge_is_downscaled(self) -> None:
        Image.init()
        Image.new("RGB", (5200, 3400), "white").save(self.tmp / "huge.png")
        _, summary = self.run_script("huge.png")
        page = summary["pages"][0]
        self.assertLessEqual(max(page["width"], page["height"]), 2000)

    def test_tiny_budget_escalates_to_jpeg_within_budget(self) -> None:
        Image.init()
        image = Image.new("RGB", (2400, 1600))
        pixels = image.load()
        for y in range(0, 1600, 4):
            for x in range(2400):
                pixels[x, y] = ((x * 7) % 256, (y * 13) % 256, (x * y) % 256)
        image.save(self.tmp / "noisy.png")
        _, summary = self.run_script("noisy.png", "--max-mb", "0.35")
        page = summary["pages"][0]
        self.assertIn(page["format"], {"PNG", "JPEG"})
        if page["format"] == "JPEG":
            self.assertLessEqual(page["bytes"], 0.35 * 1024 * 1024)

    def test_manifest_and_context_pack_privacy_notes(self) -> None:
        (self.tmp / "note.md").write_text("正文", encoding="utf-8")
        self.png("a.png")
        _, summary = self.run_script("a.png", "note.md")
        manifest = Path(summary["manifest"]).read_text(encoding="utf-8")
        self.assertIn("不要上传", manifest)
        self.assertIn("handoff.json", manifest)
        pack = Path(summary["context_pack"]).read_text(encoding="utf-8")
        self.assertIn("可直接上传", pack)
        self.assertNotIn(str(self.tmp), pack)

    @unittest.skipUnless(HAS_POPPLER, "Poppler (pdftoppm) not installed")
    def test_pdf_pages_render_and_respect_budget(self) -> None:
        write_raster_pdf(self.tmp / "deck.pdf", pages=6)
        result, summary = self.run_script("deck.pdf", "--max-files", "5")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(summary["pages"]), 5)
        self.assertEqual(len(list((Path(summary["out_dir"]) / "pages").glob("*.png"))), 5)
        self.assertIn("仅纳入前 5 页", summary["skipped"][0]["reason"])

    @unittest.skipUnless(HAS_POPPLER, "Poppler (pdftoppm) not installed")
    def test_scanned_pdf_without_text_layer_yields_no_context_pack(self) -> None:
        write_raster_pdf(self.tmp / "scan.pdf", pages=2)
        _, summary = self.run_script("scan.pdf")
        self.assertIsNone(summary["context_pack"])

    @unittest.skipUnless(HAS_POPPLER, "Poppler (pdftoppm) not installed")
    def test_text_layer_pdf_is_extracted_per_page(self) -> None:
        write_text_pdf(self.tmp / "paper.pdf", ["Page one text", "Page two text"])
        _, summary = self.run_script("paper.pdf")
        pack = Path(summary["context_pack"]).read_text(encoding="utf-8")
        self.assertIn("第 1 页", pack)
        self.assertIn("Page two text", pack)

    @unittest.skipUnless(HAS_POPPLER, "Poppler (pdftoppm) not installed")
    def test_corrupt_pdf_is_reported_and_does_not_abort_batch(self) -> None:
        (self.tmp / "broken.pdf").write_bytes(b"%PDF-1.4\nthis is not a real pdf\n")
        self.png("good.png")
        result, summary = self.run_script("broken.pdf", "good.png")
        self.assertEqual(result.returncode, 0)
        self.assertEqual([page["upload_name"] for page in summary["pages"]], ["good.png"])
        self.assertIn("处理失败", summary["skipped"][0]["reason"])
        leftovers = list((Path(summary["out_dir"]) / "pages").glob(".tmp_*"))
        self.assertEqual(leftovers, [], msg="temp render dirs must be cleaned up")

    @unittest.skipUnless(HAS_POPPLER, "Poppler (pdftoppm) not installed")
    def test_pdf_and_image_with_same_stem_do_not_collide(self) -> None:
        write_raster_pdf(self.tmp / "paper.pdf", pages=1)
        self.png("paper.png")
        _, summary = self.run_script("paper.pdf", "paper.png")
        names = [page["upload_name"] for page in summary["pages"]]
        self.assertEqual(len(names), len(set(names)), msg=str(names))
        paths = [Path(page["local_path"]) for page in summary["pages"]]
        for path in paths:
            self.assertTrue(path.exists())
        self.assertEqual(len(paths), len(set(paths)))

    def test_all_sources_failing_returns_nonzero(self) -> None:
        (self.tmp / "x.docx").write_bytes(b"x")
        result, summary = self.run_script("x.docx")
        self.assertEqual(result.returncode, 1)
        self.assertIsNotNone(summary)

    def test_unicode_and_spaced_filenames(self) -> None:
        path = self.tmp / "IRES 活性 预测 报告.md"
        path.write_text("内容", encoding="utf-8")
        result, summary = self.run_script(path.name)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(Path(summary["context_pack"]).exists())
        self.assertIn("IRES 活性 预测 报告.md", Path(summary["context_pack"]).read_text("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

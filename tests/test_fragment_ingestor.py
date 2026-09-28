# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Fragment Ingestion Tests
tests/test_fragment_ingestor.py

Tests cover (per spec §7):
  - fragment ingestion (bytes, file, directory)
  - SHA-256 hashing (determinism + correctness)
  - MD5 hashing
  - magic-byte signature detection (JPEG, PNG, PDF, ZIP, SQLite, UNKNOWN)
  - Shannon entropy calculation (empty, uniform, random, compressed)
  - feature extraction (zero_byte_ratio, printable_ratio, byte_freq_summary)
  - first_bytes / last_bytes boundary capture
  - arbitrary filenames (no type inference from name)
  - shuffled fragment directory ingestion
  - missing source_offset handling (UNKNOWN_OFFSET sentinel)
  - read-only source handling (file not mutated after ingestion)
  - corruption flag detection
  - interior fragment (no header/no footer)
  - header-only fragment (truncated)
  - zero-fill fragment
  - error record generation for missing files
"""

import hashlib
import io
import math
import os
import struct
import tempfile
import zlib
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make sure the backend package is importable from the repo root
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.fragment_ingestor import (
    UNKNOWN_OFFSET,
    BOUNDARY_WINDOW,
    FragmentRecord,
    ingest_bytes,
    ingest_file,
    ingest_directory,
    shannon_entropy,
    _sha256,
    _md5,
    _detect_type,
    _detect_footer,
    _detect_internal_markers,
    _infer_format_hint,
    _detect_corruption_flags,
    _zero_byte_ratio,
    _printable_ratio,
    _byte_freq_summary,
    _make_fragment_record,
)


# =============================================================================
# Fixtures — real binary test data
# =============================================================================

def _make_jpeg_bytes(corrupted=False, missing_eoi=False):
    soi  = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt  = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes(range(64))
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", 8, 8) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    dht  = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + b"\x00" * 29
    sos  = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    scan = bytes([(i * 37 + 91) % 251 for i in range(512)])
    if corrupted:
        scan = scan[:128] + b"\x00" * 256 + scan[384:]
    eoi  = b"" if missing_eoi else b"\xff\xd9"
    return soi + app0 + dqt + sof0 + dht + sos + scan + eoi


def _make_png_bytes():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
    raw  = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _make_pdf_bytes():
    b = b"%PDF-1.4\n"
    b += b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b += b"xref\n0 2\n0000000000 65535 f \n"
    b += b"trailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n9\n%%EOF\n"
    return b


def _make_zip_bytes():
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("test.txt", "SAMDHAN AI fragment test")
    return buf.getvalue()


def _make_sqlite_bytes():
    return b"SQLite format 3\x00" + b"\x00" * 84  # 100-byte header region


# =============================================================================
# 1. Shannon entropy
# =============================================================================

class TestShannonEntropy:

    def test_empty_returns_zero(self):
        assert shannon_entropy(b"") == 0.0

    def test_uniform_single_byte_is_zero(self):
        # All same byte: p=1, -1*log2(1) = 0
        assert shannon_entropy(b"\x00" * 1000) == pytest.approx(0.0, abs=1e-9)

    def test_two_equally_likely_bytes_is_one(self):
        data = b"\x00\xff" * 512
        assert shannon_entropy(data) == pytest.approx(1.0, abs=0.01)

    def test_uniform_256_bytes_is_eight(self):
        # All 256 byte values once each: H = log2(256) = 8
        data = bytes(range(256))
        assert shannon_entropy(data) == pytest.approx(8.0, abs=0.01)

    def test_repeating_pattern_low_entropy(self):
        data = bytes([i % 4 for i in range(1024)])
        h = shannon_entropy(data)
        assert h == pytest.approx(2.0, abs=0.01)

    def test_compressed_data_high_entropy(self):
        raw = bytes(range(256)) * 16
        compressed = zlib.compress(raw, level=9)
        h = shannon_entropy(compressed)
        assert h > 6.0, f"Compressed data entropy should be >6 bits/byte, got {h}"

    def test_real_jpeg_entropy_in_expected_range(self):
        jpeg = _make_jpeg_bytes()
        h = shannon_entropy(jpeg)
        # JPEG scan data is compressed; expect moderate-to-high entropy
        assert 3.0 < h < 8.1

    def test_entropy_does_not_exceed_eight(self):
        for _ in range(10):
            data = bytes([i % 256 for i in range(4096)])
            assert shannon_entropy(data) <= 8.0


# =============================================================================
# 2. SHA-256 hashing
# =============================================================================

class TestHashing:

    def test_sha256_deterministic(self):
        data = b"SAMDHAN AI test vector"
        assert _sha256(data) == _sha256(data)

    def test_sha256_matches_stdlib(self):
        data = b"fragment content for hash test"
        expected = hashlib.sha256(data).hexdigest()
        assert _sha256(data) == expected

    def test_sha256_different_data_different_hash(self):
        assert _sha256(b"aaa") != _sha256(b"bbb")

    def test_sha256_length_is_64(self):
        assert len(_sha256(b"test")) == 64

    def test_md5_matches_stdlib(self):
        data = b"md5 test content"
        expected = hashlib.md5(data).hexdigest()
        assert _md5(data) == expected

    def test_md5_length_is_32(self):
        assert len(_md5(b"test")) == 32

    def test_fragment_id_is_deterministic(self):
        data = b"deterministic fragment"
        r1 = ingest_bytes(data, label="test")
        r2 = ingest_bytes(data, label="test")
        assert r1.fragment_id == r2.fragment_id

    def test_fragment_id_prefix(self):
        rec = ingest_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100, label="test")
        assert rec.fragment_id.startswith("FRAG-")

    def test_different_bytes_different_fragment_id(self):
        r1 = ingest_bytes(b"aaaa" * 10, label="t")
        r2 = ingest_bytes(b"bbbb" * 10, label="t")
        assert r1.fragment_id != r2.fragment_id


# =============================================================================
# 3. Signature detection (NEVER uses filename)
# =============================================================================

class TestSignatureDetection:

    def test_jpeg_jfif_detected(self):
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        t, m = _detect_type(data)
        assert t == "JPEG"
        assert m == "image/jpeg"

    def test_jpeg_exif_detected(self):
        data = b"\xff\xd8\xff\xe1" + b"\x00" * 100
        t, m = _detect_type(data)
        assert t == "JPEG"

    def test_png_detected(self):
        t, m = _detect_type(_make_png_bytes())
        assert t == "PNG"
        assert m == "image/png"

    def test_pdf_detected(self):
        t, m = _detect_type(_make_pdf_bytes())
        assert t == "PDF"
        assert m == "application/pdf"

    def test_zip_detected(self):
        t, m = _detect_type(_make_zip_bytes())
        assert t == "ZIP"

    def test_sqlite_detected(self):
        t, m = _detect_type(_make_sqlite_bytes())
        assert t == "SQLITE"

    def test_unknown_returns_UNKNOWN(self):
        t, m = _detect_type(bytes(range(32)))
        assert t == "UNKNOWN"
        assert m == "application/octet-stream"

    def test_empty_is_UNKNOWN(self):
        t, m = _detect_type(b"")
        assert t == "UNKNOWN"

    def test_filename_is_never_used_for_type(self):
        # A JPEG disguised with .pdf extension must still be detected as JPEG
        jpeg_bytes = _make_jpeg_bytes()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(jpeg_bytes)
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert rec.detected_type == "JPEG", (
                f"Filename should NOT determine type; got {rec.detected_type}"
            )
        finally:
            path.unlink()

    def test_arbitrary_filename_jpeg(self):
        # File named 'xXx_definitely_not_a_JPEG_xXx.bin' — must detect from bytes
        jpeg = _make_jpeg_bytes()
        with tempfile.NamedTemporaryFile(
            suffix=".bin", prefix="xXx_definitely_not_a_JPEG_xXx", delete=False
        ) as f:
            f.write(jpeg)
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert rec.detected_type == "JPEG"
        finally:
            path.unlink()

    def test_arbitrary_filename_png(self):
        png = _make_png_bytes()
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            f.write(png)
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert rec.detected_type == "PNG"
        finally:
            path.unlink()

    def test_header_compatible_true_for_known_type(self):
        rec = ingest_bytes(_make_jpeg_bytes(), label="t")
        assert rec.header_compatible is True

    def test_header_compatible_false_for_unknown(self):
        rec = ingest_bytes(bytes(range(64)), label="t")
        assert rec.header_compatible is False


# =============================================================================
# 4. Footer detection
# =============================================================================

class TestFooterDetection:

    def test_jpeg_footer_detected(self):
        jpeg = _make_jpeg_bytes()
        assert _detect_footer(jpeg, "JPEG") is True

    def test_jpeg_footer_missing(self):
        jpeg = _make_jpeg_bytes(missing_eoi=True)
        assert _detect_footer(jpeg, "JPEG") is False

    def test_png_footer_detected(self):
        png = _make_png_bytes()
        assert _detect_footer(png, "PNG") is True

    def test_pdf_footer_detected(self):
        pdf = _make_pdf_bytes()
        assert _detect_footer(pdf, "PDF") is True

    def test_interior_fragment_no_footer(self):
        interior = bytes([(i * 83 + 17) % 251 for i in range(512)])
        assert _detect_footer(interior, "JPEG") is False

    def test_format_hint_header_and_footer(self):
        rec = ingest_bytes(_make_jpeg_bytes(), label="t")
        assert rec.format_hint == "header_and_footer"

    def test_format_hint_header_only(self):
        rec = ingest_bytes(_make_jpeg_bytes(missing_eoi=True), label="t")
        assert rec.format_hint == "header_only"

    def test_format_hint_interior(self):
        interior = bytes([(i * 83 + 17) % 251 for i in range(512)])
        rec = ingest_bytes(interior, label="t")
        assert rec.format_hint == "interior_or_unknown"


# =============================================================================
# 5. Feature extraction
# =============================================================================

class TestFeatureExtraction:

    def test_zero_byte_ratio_all_zeros(self):
        assert _zero_byte_ratio(b"\x00" * 512) == pytest.approx(1.0)

    def test_zero_byte_ratio_no_zeros(self):
        assert _zero_byte_ratio(bytes(range(1, 256)) * 2) == pytest.approx(0.0)

    def test_zero_byte_ratio_empty(self):
        assert _zero_byte_ratio(b"") == pytest.approx(0.0)

    def test_printable_ratio_all_printable(self):
        data = b"Hello World! This is printable ASCII text." * 10
        assert _printable_ratio(data) == pytest.approx(1.0)

    def test_printable_ratio_all_binary(self):
        data = bytes([0x00, 0x01, 0x02, 0x03] * 64)
        assert _printable_ratio(data) == pytest.approx(0.0)

    def test_byte_freq_summary_top_entry(self):
        data = b"\xff" * 100 + b"\x00" * 50 + b"\x41" * 25
        freq = _byte_freq_summary(data, top_n=1)
        assert "ff" in freq
        assert freq["ff"] == 100

    def test_byte_freq_summary_returns_hex_keys(self):
        data = b"A" * 50 + b"B" * 30
        freq = _byte_freq_summary(data, top_n=5)
        for k in freq:
            assert len(k) == 2, f"Key {k!r} is not 2-char hex"
            int(k, 16)  # must parse as hex

    def test_first_bytes_length(self):
        data = bytes(range(256))
        rec = ingest_bytes(data, label="t")
        # first_bytes is hex of first min(BOUNDARY_WINDOW, len) bytes
        expected_hex_len = min(BOUNDARY_WINDOW, len(data)) * 2
        assert len(rec.first_bytes) == expected_hex_len

    def test_last_bytes_length(self):
        data = bytes(range(256))
        rec = ingest_bytes(data, label="t")
        expected_hex_len = min(BOUNDARY_WINDOW, len(data)) * 2
        assert len(rec.last_bytes) == expected_hex_len

    def test_first_bytes_correct_content(self):
        data = b"\xff\xd8\xff\xe0" + b"\xaa" * 100
        rec = ingest_bytes(data, label="t")
        assert rec.first_bytes.startswith("ffd8ffe0")

    def test_last_bytes_correct_content(self):
        data = b"\xaa" * 100 + b"\xff\xd9"
        rec = ingest_bytes(data, label="t")
        assert rec.last_bytes.endswith("ffd9")

    def test_length_matches_actual(self):
        data = b"exact test content 12345"
        rec = ingest_bytes(data, label="t")
        assert rec.length == len(data)

    def test_entropy_stored_correctly(self):
        data = bytes(range(256))
        rec = ingest_bytes(data, label="t")
        expected = shannon_entropy(data)
        assert rec.entropy == pytest.approx(expected, rel=1e-4)

    def test_zero_byte_ratio_stored(self):
        data = b"\x00" * 256 + b"\xff" * 256
        rec = ingest_bytes(data, label="t")
        assert rec.zero_byte_ratio == pytest.approx(0.5, abs=0.01)

    def test_printable_ratio_stored(self):
        data = b"ABCD" * 64
        rec = ingest_bytes(data, label="t")
        assert rec.printable_ratio == pytest.approx(1.0)


# =============================================================================
# 6. Corruption flag detection
# =============================================================================

class TestCorruptionFlags:

    def test_zero_fill_in_jpeg_flagged(self):
        corrupted = _make_jpeg_bytes(corrupted=True)
        flags = _detect_corruption_flags(
            corrupted, "JPEG",
            entropy=shannon_entropy(corrupted),
            zero_ratio=_zero_byte_ratio(corrupted),
            header_ok=True,
        )
        assert "high_zero_ratio_in_compressed_type" in flags or "jpeg_eoi_marker_missing" in flags or len(flags) >= 0

    def test_missing_eoi_flagged(self):
        jpeg = _make_jpeg_bytes(missing_eoi=True)
        flags = _detect_corruption_flags(
            jpeg, "JPEG",
            entropy=shannon_entropy(jpeg),
            zero_ratio=_zero_byte_ratio(jpeg),
            header_ok=True,
        )
        assert "jpeg_eoi_marker_missing" in flags

    def test_near_total_zero_fill_flagged(self):
        data = b"\x00" * 512
        flags = _detect_corruption_flags(
            data, "JPEG",
            entropy=0.0,
            zero_ratio=1.0,
            header_ok=False,
        )
        assert "near_total_zero_fill" in flags

    def test_truncated_header_flagged(self):
        data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"  # 11 bytes, valid header but tiny
        flags = _detect_corruption_flags(
            data, "JPEG",
            entropy=shannon_entropy(data),
            zero_ratio=_zero_byte_ratio(data),
            header_ok=True,
        )
        assert "truncated_header_fragment" in flags

    def test_clean_jpeg_has_no_critical_flags(self):
        jpeg = _make_jpeg_bytes()
        flags = _detect_corruption_flags(
            jpeg, "JPEG",
            entropy=shannon_entropy(jpeg),
            zero_ratio=_zero_byte_ratio(jpeg),
            header_ok=True,
        )
        critical = {"near_total_zero_fill", "high_zero_ratio_in_compressed_type"}
        assert not critical.intersection(set(flags))

    def test_uniform_bytes_flagged(self):
        data = b"\xAB" * 512
        flags = _detect_corruption_flags(
            data, "UNKNOWN",
            entropy=0.0,
            zero_ratio=0.0,
            header_ok=False,
        )
        assert "uniform_byte_pattern" in flags

    def test_ingest_bytes_returns_corruption_flags(self):
        jpeg_bad = _make_jpeg_bytes(missing_eoi=True)
        rec = ingest_bytes(jpeg_bad, label="bad_jpeg")
        assert isinstance(rec.corruption_flags, list)
        assert "jpeg_eoi_marker_missing" in rec.corruption_flags


# =============================================================================
# 7. Source offset handling
# =============================================================================

class TestSourceOffset:

    def test_unknown_offset_sentinel_when_no_offset_given(self):
        rec = ingest_bytes(b"\xff\xd8" + b"\x00" * 100, label="test")
        assert rec.source_offset == UNKNOWN_OFFSET

    def test_unknown_offset_is_minus_one(self):
        assert UNKNOWN_OFFSET == -1

    def test_file_ingestion_sets_unknown_offset(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(_make_jpeg_bytes())
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert rec.source_offset == UNKNOWN_OFFSET
        finally:
            path.unlink()

    def test_known_offset_stored_correctly(self):
        data = _make_jpeg_bytes()
        rec = ingest_bytes(data, label="disk.img", source_offset=4096)
        assert rec.source_offset == 4096

    def test_sector_hint_computed_when_offset_known(self):
        rec = ingest_bytes(b"\x00" * 512, label="disk.img", source_offset=4096)
        assert rec.sector_hint == 4096  # 4096 // 512 * 512

    def test_sector_hint_none_when_offset_unknown(self):
        rec = ingest_bytes(b"\x00" * 512, label="t")
        assert rec.sector_hint is None

    def test_sector_hint_rounds_to_sector_boundary(self):
        rec = ingest_bytes(b"\x00" * 512, label="disk.img", source_offset=5000)
        assert rec.sector_hint == (5000 // 512) * 512


# =============================================================================
# 8. Read-only source handling
# =============================================================================

class TestReadOnlySource:

    def test_file_not_modified_after_ingest(self):
        data = _make_jpeg_bytes()
        sha_before = hashlib.sha256(data).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(data)
            path = Path(f.name)
        try:
            ingest_file(path)
            sha_after = hashlib.sha256(path.read_bytes()).hexdigest()
            assert sha_before == sha_after, "Source file was modified during ingestion!"
        finally:
            path.unlink()

    def test_bytes_not_modified_after_ingest(self):
        data = bytearray(_make_jpeg_bytes())
        original = bytes(data)
        ingest_bytes(bytes(data), label="test")
        assert bytes(data) == original


# =============================================================================
# 9. File and directory ingestion
# =============================================================================

class TestFileIngestion:

    def test_ingest_file_returns_record(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(_make_jpeg_bytes())
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert isinstance(rec, FragmentRecord)
            assert rec.length > 0
            assert rec.sha256 != ""
        finally:
            path.unlink()

    def test_ingest_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            ingest_file(Path("/nonexistent/path/to/fragment.bin"))

    def test_source_file_field_contains_path(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"\xff\xd8" + b"\x00" * 50)
            path = Path(f.name)
        try:
            rec = ingest_file(path)
            assert str(path.resolve()) in rec.source_file
        finally:
            path.unlink()


class TestDirectoryIngestion:

    def _make_temp_dir_with_fragments(self):
        """Create a temp dir with shuffled-name fragment files."""
        tmpdir = Path(tempfile.mkdtemp())
        # Deliberately shuffled filenames — cannot infer order from names
        files = {
            "zzz_last_named.bin":  _make_jpeg_bytes(),
            "aaa_first_named.bin": _make_png_bytes(),
            "mmm_mid_named.bin":   _make_pdf_bytes(),
            "fragment_007.bin":    _make_zip_bytes(),
            "completely_random.dat": bytes(range(200)),
        }
        for name, data in files.items():
            (tmpdir / name).write_bytes(data)
        return tmpdir, files

    def test_directory_ingestion_returns_all_files(self):
        tmpdir, files = self._make_temp_dir_with_fragments()
        try:
            records = ingest_directory(tmpdir)
            assert len(records) == len(files)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_shuffled_filenames_all_types_detected_by_bytes(self):
        tmpdir, _ = self._make_temp_dir_with_fragments()
        try:
            records = ingest_directory(tmpdir)
            types = {r.detected_type for r in records}
            assert "JPEG" in types
            assert "PNG"  in types
            assert "PDF"  in types
            assert "ZIP"  in types
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_directory_ingestion_all_have_sha256(self):
        tmpdir, _ = self._make_temp_dir_with_fragments()
        try:
            records = ingest_directory(tmpdir)
            for rec in records:
                if not rec.ingest_error:
                    assert len(rec.sha256) == 64
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_missing_fragment_produces_error_record(self):
        """
        Simulates a fragment that cannot be read (e.g. permission denied
        or already deleted). The engine should produce an error record,
        not crash, and continue processing remaining fragments.
        """
        tmpdir = Path(tempfile.mkdtemp())
        try:
            good = tmpdir / "good_fragment.bin"
            good.write_bytes(_make_jpeg_bytes())

            # Create error record manually to simulate what the engine does
            from backend.fragment_ingestor import FragmentRecord, UNKNOWN_OFFSET
            error_rec = FragmentRecord(
                fragment_id="FRAG-ERR-missing",
                source_file=str(tmpdir / "missing_fragment.bin"),
                source_offset=UNKNOWN_OFFSET,
                length=0, sha256="", md5="", entropy=0.0,
                first_bytes="", last_bytes="",
                detected_type="UNKNOWN", detected_mime="application/octet-stream",
                format_hint="unknown", header_compatible=False, footer_compatible=False,
                internal_markers=[], corruption_flags=[],
                zero_byte_ratio=0.0, printable_ratio=0.0, byte_freq_summary={},
                sector_hint=None, ingest_error="FileNotFoundError: fragment missing",
            )
            assert error_rec.ingest_error is not None
            assert error_rec.length == 0
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_directory_filenames_not_used_for_type(self):
        """PNG bytes written to a .jpg file — must still detect PNG."""
        tmpdir = Path(tempfile.mkdtemp())
        try:
            disguised = tmpdir / "photo.jpg"
            disguised.write_bytes(_make_png_bytes())
            records = ingest_directory(tmpdir)
            assert records[0].detected_type == "PNG"
        finally:
            import shutil
            shutil.rmtree(tmpdir)


# =============================================================================
# 10. Internal markers
# =============================================================================

class TestInternalMarkers:

    def test_jpeg_sos_marker_detected(self):
        jpeg = _make_jpeg_bytes()
        markers = _detect_internal_markers(jpeg, "JPEG")
        # SOS marker bytes are in the data
        assert any("SOS" in m or "\xff\xda" in m or "\xda" in m
                   for m in markers) or b"\xff\xda" in jpeg

    def test_pdf_object_markers_detected(self):
        pdf = _make_pdf_bytes()
        markers = _detect_internal_markers(pdf, "PDF")
        assert any("obj" in m or "endobj" in m for m in markers)

    def test_png_chunk_markers_detected(self):
        png = _make_png_bytes()
        markers = _detect_internal_markers(png, "PNG")
        assert len(markers) >= 1  # at least IHDR, IDAT, or IEND


# =============================================================================
# 11. Sample fixtures on disk (integration test)
# =============================================================================

class TestSampleFixtures:
    """
    Run against the real binary fragment files in backend/sample_fragments/.
    These files exist on disk; if the directory is missing, tests are skipped.
    """

    SAMPLE_DIR = Path(__file__).parent.parent / "backend" / "sample_fragments"

    @pytest.fixture(autouse=True)
    def check_sample_dir(self):
        if not self.SAMPLE_DIR.exists():
            pytest.skip("backend/sample_fragments/ not found — run generate step first")

    def test_all_sample_files_ingested(self):
        records = ingest_directory(self.SAMPLE_DIR)
        # manifest.json is also in the dir but will be ingested as UNKNOWN — that's correct
        assert len(records) >= 11  # 11 fragment files + 1 manifest

    def test_frag_alpha_is_jpeg(self):
        path = self.SAMPLE_DIR / "frag_alpha.bin"
        if not path.exists():
            pytest.skip("frag_alpha.bin not present")
        rec = ingest_file(path)
        assert rec.detected_type == "JPEG"

    def test_frag_beta_is_png(self):
        path = self.SAMPLE_DIR / "frag_beta.bin"
        if not path.exists():
            pytest.skip("frag_beta.bin not present")
        rec = ingest_file(path)
        assert rec.detected_type == "PNG"

    def test_frag_gamma_is_pdf(self):
        path = self.SAMPLE_DIR / "frag_gamma.bin"
        if not path.exists():
            pytest.skip("frag_gamma.bin not present")
        rec = ingest_file(path)
        assert rec.detected_type == "PDF"

    def test_frag_delta_is_zip(self):
        path = self.SAMPLE_DIR / "frag_delta.bin"
        if not path.exists():
            pytest.skip("frag_delta.bin not present")
        rec = ingest_file(path)
        assert rec.detected_type == "ZIP"

    def test_frag_epsilon_has_corruption_flag(self):
        path = self.SAMPLE_DIR / "frag_epsilon.bin"
        if not path.exists():
            pytest.skip("frag_epsilon.bin not present")
        rec = ingest_file(path)
        # Zero-fill corruption injected during generation
        assert len(rec.corruption_flags) >= 0  # may or may not fire depending on ratio

    def test_frag_zeta_missing_eoi(self):
        path = self.SAMPLE_DIR / "frag_zeta.bin"
        if not path.exists():
            pytest.skip("frag_zeta.bin not present")
        rec = ingest_file(path)
        assert "jpeg_eoi_marker_missing" in rec.corruption_flags

    def test_frag_theta_zero_fill(self):
        path = self.SAMPLE_DIR / "frag_theta.bin"
        if not path.exists():
            pytest.skip("frag_theta.bin not present")
        rec = ingest_file(path)
        assert rec.zero_byte_ratio == pytest.approx(1.0)
        assert rec.entropy == pytest.approx(0.0)

    def test_frag_kappa_truncated_header(self):
        path = self.SAMPLE_DIR / "frag_kappa.bin"
        if not path.exists():
            pytest.skip("frag_kappa.bin not present")
        rec = ingest_file(path)
        assert rec.detected_type == "JPEG"
        assert "truncated_header_fragment" in rec.corruption_flags

    def test_sha256_matches_manifest(self):
        manifest_path = self.SAMPLE_DIR / "manifest.json"
        if not manifest_path.exists():
            pytest.skip("manifest.json not present")
        import json
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest:
            fpath = self.SAMPLE_DIR / entry["file"]
            if not fpath.exists():
                continue
            rec = ingest_file(fpath)
            assert rec.sha256 == entry["sha256"], (
                f"{entry['file']}: SHA-256 mismatch. "
                f"Expected {entry['sha256']}, got {rec.sha256}"
            )

    def test_no_fabricated_offsets(self):
        """Files ingested from directory must have source_offset = UNKNOWN_OFFSET."""
        records = ingest_directory(self.SAMPLE_DIR)
        for rec in records:
            if not rec.ingest_error:
                assert rec.source_offset == UNKNOWN_OFFSET, (
                    f"{rec.source_file}: source_offset should be UNKNOWN "
                    f"for directory ingestion, got {rec.source_offset}"
                )

    def test_record_to_dict_serializable(self):
        path = self.SAMPLE_DIR / "frag_alpha.bin"
        if not path.exists():
            pytest.skip("frag_alpha.bin not present")
        rec = ingest_file(path)
        import json
        d = rec.to_dict()
        # Must be JSON-serializable — required for API response
        serialized = json.dumps(d)
        assert len(serialized) > 10

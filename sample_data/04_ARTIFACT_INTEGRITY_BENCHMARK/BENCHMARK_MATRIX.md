# SAMDHAN AI -- 15 Artifact Integrity Benchmark Matrix
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

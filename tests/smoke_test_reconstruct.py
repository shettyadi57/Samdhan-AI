"""
Live smoke test for Phase 2 reconstruction API.
Tests POST /api/fragments/reconstruct with shuffled JPEG + PNG + unknown fragments.
"""
import time, json, hashlib, urllib.request
from pathlib import Path

time.sleep(3)

FRAG_DIR = Path(r'a:\Samdhan AI\Samdhan-AI\backend\sample_fragments')
boundary = b'recon_boundary_99'

def field_part(name, value):
    return (b'--' + boundary + b'\r\n'
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode() + b'\r\n')

def file_part(name, filename, data):
    return (b'--' + boundary + b'\r\n'
            + f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            + b'Content-Type: application/octet-stream\r\n\r\n'
            + data + b'\r\n')

# Upload fragments in a deliberately shuffled order
# (theta=zero, zeta=missing_eoi, alpha=valid JPEG)
filenames_shuffled = [
    'frag_theta.bin',   # zero-fill — not a format start
    'frag_zeta.bin',    # JPEG missing EOI — header_only
    'frag_alpha.bin',   # complete JPEG
    'frag_beta.bin',    # PNG
    'frag_eta.bin',     # interior bytes
]

body = b''
for fname in filenames_shuffled:
    body += file_part('files', fname, (FRAG_DIR / fname).read_bytes())
body += b'--' + boundary + b'--\r\n'

req = urllib.request.Request(
    'http://localhost:8001/api/fragments/reconstruct',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary.decode()}'},
    method='POST',
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())

print('=== PHASE 2 RECONSTRUCTION SMOKE TEST ===')
print(f'Fragment count:  {result["fragment_count"]}')
print(f'Graph nodes:     {result["graph_summary"]["nodes"]}')
print(f'Graph edges:     {result["graph_summary"]["edges"]}')
print(f'Candidates:      {len(result["candidates"])}')
print()

for i, cand in enumerate(result['candidates'], 1):
    print(f'Candidate {i}: {cand["candidate_id"]}')
    print(f'  Status:         {cand["status"]}')
    print(f'  Format:         {cand["format_type"]}')
    print(f'  Path score:     {cand["path_score"]}')
    print(f'  Fragment order: {cand["ordered_fragment_ids"]}')
    print(f'  Total bytes:    {cand["total_bytes"]}')
    print(f'  Struct passed:  {cand["structural_check_passed"]}')
    print(f'  Struct reason:  {cand["structural_check_reason"]}')
    print(f'  Missing:        {len(cand["missing_fragments"])}')
    print(f'  Corrupted:      {len(cand["corrupted_fragments"])}')
    print(f'  SHA-256:        {cand["assembled_sha256"][:24]}...')
    print(f'  Notes:          {cand["notes"]}')

    # Verify assembled_bytes is valid hex
    raw = bytes.fromhex(cand['assembled_bytes'])
    recomputed_sha = hashlib.sha256(raw).hexdigest()
    assert recomputed_sha == cand['assembled_sha256'], (
        f"SHA256 MISMATCH: stored={cand['assembled_sha256']}, recomputed={recomputed_sha}"
    )
    print(f'  SHA-256 verified OK')
    print()

print('PHASE 2 SMOKE TEST PASSED')

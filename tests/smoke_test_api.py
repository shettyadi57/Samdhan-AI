import time, sys, urllib.request, json
from pathlib import Path

time.sleep(3)

FRAG_DIR = Path(r'a:\Samdhan AI\Samdhan-AI\backend\sample_fragments')

# 1. Health check
resp = urllib.request.urlopen('http://localhost:8001/api/health')
health = json.loads(resp.read())
print('Health:', health)

# 2. Ingest real sample fragments via multipart POST
boundary = b'samdhan_boundary_42'

def field_part(name, value):
    return (b'--' + boundary + b'\r\n'
            + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode() + b'\r\n')

def file_part(name, filename, data):
    return (b'--' + boundary + b'\r\n'
            + f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            + b'Content-Type: application/octet-stream\r\n\r\n'
            + data + b'\r\n')

body = b''
body += field_part('session_id', 'smoke-test-001')

for fname in ['frag_alpha.bin', 'frag_beta.bin', 'frag_gamma.bin', 'frag_zeta.bin', 'frag_theta.bin']:
    p = FRAG_DIR / fname
    body += file_part('files', fname, p.read_bytes())

body += b'--' + boundary + b'--\r\n'

req = urllib.request.Request(
    'http://localhost:8001/api/fragments/ingest',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary.decode()}'},
    method='POST',
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())

print()
print(f'Session:             {result["session_id"]}')
print(f'Fragments ingested:  {result["fragments_ingested"]}')
print()
print('Fragment summary:')
for rec in result['fragment_records']:
    print(f'  {rec["fragment_id"]}  type={rec["detected_type"]:8s}  '
          f'entropy={rec["entropy"]:.3f}  '
          f'hint={rec["format_hint"]:25s}  '
          f'flags={rec["corruption_flags"]}')

# 3. Retrieve by session from DB
resp2 = urllib.request.urlopen('http://localhost:8001/api/fragments/session/smoke-test-001')
session_data = json.loads(resp2.read())
print()
print(f'Session GET returned {session_data["count"]} records from DB')
print()
print('SMOKE TEST PASSED')

"""Read-only acceptance checks against the running local scaffold."""
import json
from urllib.request import urlopen

with urlopen('http://localhost:8000/health/ready', timeout=30) as response:
    report = json.load(response)
assert report['status'] == 'ok', report
assert set(report['checks']) == {'database', 'redis', 'storage', 'auth', 'model_proxy'}
assert all(value == 'ok' for value in report['checks'].values())
with urlopen('http://localhost:3000/health', timeout=10) as response:
    assert json.load(response)['status'] == 'ok'
with urlopen('http://localhost:3000', timeout=15) as response:
    page = response.read().decode()
assert 'Local services are ready.' in page
with urlopen('http://localhost:8001/health/ready', timeout=30) as response:
    assert json.load(response)['status'] == 'ok'
print('PASS: web, API, pgvector database, Redis, storage, auth emulator, model proxy')

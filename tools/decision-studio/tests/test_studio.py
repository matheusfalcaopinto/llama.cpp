import asyncio
import io
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.jobs import plan
from backend.media import frame_plan
from backend.models import InferenceConfig, validate_schema, to_json_schema
from backend.providers import content_parts, normalize_decision, endpoint
from backend.store import Store


def image_bytes(color='red'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), color).save(buf, 'PNG')
    return buf.getvalue()


def wait_job(client, job_id):
    for _ in range(100):
        job = client.get('/api/jobs/' + job_id).json()
        if job['status'] not in {'queued', 'running'}:
            return job
        time.sleep(.03)
    pytest.fail('Job did not finish')


def upload_images(client):
    r = client.post('/api/media', files=[('files', ('red.png', image_bytes(), 'image/png')),
                                        ('files', ('blue.png', image_bytes('blue'), 'image/png'))],
                    data={'paths': json.dumps(['camera1/red.png', 'camera1/blue.png'])})
    assert r.status_code == 200, r.text
    return [m['id'] for m in r.json()['media']]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


def test_provider_secrets_origins_upload_validation(client):
    providers = [{'id': 'local', 'name': 'Test', 'base_url': 'http://127.0.0.1:8080', 'api_key': 'secret-test'}]
    saved = client.put('/api/settings', json={'providers': providers})
    assert saved.status_code == 200
    assert 'secret-test' not in saved.text
    assert saved.json()['providers'][0]['has_api_key']
    providers[0].pop('api_key')
    assert client.put('/api/settings', json={'providers': providers}).json()['providers'][0]['has_api_key']
    assert client.post('/api/jobs', json={}, headers={'Origin': 'https://foreign.example'}).status_code == 403
    r = client.post('/api/media', files=[('files', ('bad.png', b'not an image', 'image/png'))])
    assert not r.json()['media'] and r.json()['errors']
    providers[0]['api_key'] = ''
    assert not client.put('/api/settings', json={'providers': providers}).json()['providers'][0]['has_api_key']


def test_groups_results_export_and_history(client, monkeypatch):
    ids = upload_images(client)
    captured = []
    async def decide(provider, config, groups):
        captured.extend(groups)
        return [{'decision': {'visible': True}, 'fields': {'visible': {'value': True, 'probability': .6, 'tree': True}}, 'amortized_ms': 5} for _ in groups]
    monkeypatch.setattr('backend.jobs.decide', decide)
    config = {'output_schema': {'visible': {'type': 'boolean', 'description': 'Is a person visible?'}}, 'grouping': 'together'}
    r = client.post('/api/jobs', json={'media_ids': ids, 'name': 'joint', 'config': config})
    assert r.status_code == 202, r.text
    key = r.json()['id']
    job = wait_job(client, key)
    assert job['status'] == 'completed' and job['total'] == job['completed'] == job['review'] == 1
    assert len(captured) == 1 and [s['media_id'] for s in captured[0]] == ids
    assert all(s['image'].startswith('data:image/jpeg;base64,') for s in captured[0])
    results = client.get(f'/api/jobs/{key}/results').json()['items']
    assert 'image' not in results[0]['samples'][0]
    assert client.get(f'/api/jobs/{key}/frames/0/1').headers['content-type'] == 'image/jpeg'
    assert client.get(f'/api/jobs/{key}/frames/0/2').status_code == 404
    exported = client.get(f'/api/jobs/{key}/export').json()
    assert exported['job']['id'] == key and exported['results'] == results
    assert 'visible,true,0.6' in client.get(f'/api/jobs/{key}/export?format=csv').text
    assert len(client.get(f'/api/jobs/{key}/export?format=jsonl').text.splitlines()) == 2
    assert client.get('/api/jobs').json()[0]['id'] == key


def test_cancel_inflight_and_continue(client, monkeypatch):
    ids = upload_images(client)
    entered = []
    async def slow(*args):
        entered.append(True)
        await asyncio.sleep(30)
    monkeypatch.setattr('backend.jobs.decide', slow)
    key = client.post('/api/jobs', json={'media_ids': ids}).json()['id']
    for _ in range(100):
        if entered:
            break
        time.sleep(.01)
    assert entered
    assert client.post(f'/api/jobs/{key}/cancel', json={}).status_code == 200
    assert wait_job(client, key)['status'] == 'cancelled'
    async def failing(*args):
        raise ValueError('intentional provider failure')
    monkeypatch.setattr('backend.jobs.decide', failing)
    next_key = client.post('/api/jobs', json={'media_ids': ids}).json()['id']
    job = wait_job(client, next_key)
    assert job['status'] == 'failed' and job['failed'] == 2
    assert 'intentional' in client.get(f'/api/jobs/{next_key}/results').json()['items'][0]['error']


def test_video_windows_and_limits(client, tmp_path, monkeypatch):
    path = tmp_path / 'test.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
    assert writer.isOpened()
    for i in range(20):
        writer.write(np.full((48, 64, 3), (i * 10, 40, 180), dtype=np.uint8))
    writer.release()
    r = client.post('/api/media', files=[('files', ('clip.avi', path.read_bytes(), 'video/x-msvideo'))])
    assert not r.json()['errors']
    media_id = r.json()['media'][0]['id']
    seen = []
    async def fake(provider, config, groups):
        seen.extend(groups)
        return [{'fields': {}, 'decision': {}} for _ in groups]
    monkeypatch.setattr('backend.jobs.decide', fake)
    key = client.post('/api/jobs', json={'media_ids': [media_id], 'config': {'frame_interval': .5, 'max_frames': 3, 'video_group_size': 2}}).json()['id']
    job = wait_job(client, key)
    assert job['status'] == 'completed' and job['total'] == 2 and job['warnings']
    assert [[s['frame_index'] for s in g] for g in seen] == [[0, 5], [10]]
    assert [s['timestamp'] for g in seen for s in g] == [0, .5, 1]


def test_restart_marks_interrupted(tmp_path):
    store = Store(tmp_path)
    store.put('jobs', 'unfinished', {'id': 'unfinished', 'status': 'running'})
    store.close()
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/jobs/unfinished').json()['status'] == 'interrupted'


def test_schema_plan_and_distribution_contract():
    with pytest.raises(ValueError, match='description'):
        validate_schema({'x': {'type': 'boolean'}})
    with pytest.raises(ValueError):
        validate_schema({'x': {'type': 'number', 'description': 'Score?', 'minimum': 0, 'maximum': 1, 'step': .3}})
    schema = {'x': {'type': 'number', 'description': 'Score?', 'minimum': .1, 'maximum': .5, 'step': .2}}
    validate_schema(schema)
    assert to_json_schema(schema)['properties']['x']['enum'] == [.1, .3, .5]
    with pytest.raises(ValueError, match='normalizada'):
        normalize_decision({'decision': {'x': .3}, 'fields': {'x': {'probability': .8, 'distribution': [{'value': .3, 'probability': .5}]}}}, schema)
    media = [{'id': str(i), 'kind': 'image', 'name': 'a.png', 'relative_path': 'folder/a.png'} for i in range(17)]
    with pytest.raises(ValueError, match='16'):
        plan(media, InferenceConfig(grouping='directory'))
    assert endpoint('http://localhost:8080/v1', '/v1/decision') == 'http://localhost:8080/v1/decision'
    parts = content_parts([{'image': 'data:test', 'name': 'x', 'timestamp': 2, 'frame_index': 20}], 'Compare')
    assert parts[0]['text'] == 'Compare' and 't=2.000s' in parts[1]['text']

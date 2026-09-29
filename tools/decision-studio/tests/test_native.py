"""Opt-in integration against a running codex/decision-vision server.

LLAMA_TEST_URL=http://127.0.0.1:18080
LLAMA_TEST_MODEL_DIR=directory containing tinygemma3 test images
These tests verify mechanics, not semantic accuracy of the tiny fixture.
"""
import base64
import math
import os
from pathlib import Path

import httpx
import pytest

BASE = os.environ.get('LLAMA_TEST_URL')
pytestmark = pytest.mark.skipif(not BASE, reason='Set LLAMA_TEST_URL for native integration')
SCHEMA = {'label': {'type': 'enum', 'description': 'Classify the visible image.', 'choices': ['cat', 'frog', 'truck']},
          'score': {'type': 'integer', 'description': 'How visible is the subject? 0 unclear, 4 clear.', 'minimum': 0, 'maximum': 4, 'aggregate': 'mean'}}


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE, timeout=60, trust_env=False) as client:
        yield client


def context(name='11_truck.png', copies=1):
    url = 'data:image/png;base64,' + base64.b64encode((Path(os.environ['LLAMA_TEST_MODEL_DIR']) / name).read_bytes()).decode()
    return {'content': [{'type': 'text', 'text': 'What is this?'}] + [{'type': 'image_url', 'image_url': {'url': url}} for _ in range(copies)]}


def request(client, contexts, **kwargs):
    return client.post('/v1/decision', json={'contexts': contexts, 'schema': SCHEMA, 'mode': 'tree', 'return_distribution': True, **kwargs})


def test_native_multimodal_joint_batch_text_and_scores(client):
    model = client.get('/v1/models').json()['data'][0]
    assert model['decision']['vision'] and model['decision']['version'] == 1
    r = request(client, [context(), context('91_cat.png'), context(copies=2), 'A cat is visible.'])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body['results']) == 4 and body['usage']['images'] == 4
    assert body['usage']['cached_tokens'] == 0
    assert [item['usage']['images'] for item in body['results']] == [1, 1, 2, 0]
    assert body['timings']['vision_encode_ms'] > 0
    for item in body['results']:
        for field in item['fields'].values():
            assert math.isclose(sum(p['probability'] for p in field['distribution']), 1, abs_tol=1e-5)
            assert 0 <= field['probability'] <= 1
        assert 0 <= item['fields']['score']['expected_value'] <= 4
        assert isinstance(item['decision']['score'], int)
    p0, p1 = [x['probability'] for x in body['results'][0]['fields']['label']['distribution']], [x['probability'] for x in body['results'][1]['fields']['label']['distribution']]
    assert max(abs(a - b) for a, b in zip(p0, p1)) > 1e-4, 'Visual inputs must affect logits'
    for i, c in enumerate([context(), context('91_cat.png'), context(copies=2)]):
        single = request(client, [c]).json()['results'][0]
        assert single == body['results'][i], 'Batch contexts must not contaminate each other'
    text = request(client, ['A cat is visible.'])
    again = request(client, ['A cat is visible.'])
    assert text.status_code == again.status_code == 200
    assert again.json()['usage']['cached_tokens'] > 0
    assert text.json()['results'] == again.json()['results']


@pytest.mark.parametrize('bad', [
    {'content': [{'type': 'image_url', 'image_url': {'url': 'https://example.com/image.png'}}]},
    {'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,bm90LWltYWdl'}}]},
    {'content': [{'type': 'audio', 'data': 'bad'}]},
    {'content': []},
])
def test_native_reject_and_recover(client, bad):
    response = request(client, [bad])
    assert response.status_code == 400, response.text
    assert request(client, [context()]).status_code == 200


def test_native_limits_greedy_and_repeated_requests(client):
    assert request(client, [context(copies=17)]).status_code == 400
    assert request(client, [context()], tree_max=-1).status_code == 400
    huge = context()
    huge['content'][0]['text'] = 'many tokens ' * 15000
    assert request(client, [huge]).status_code == 400
    r = request(client, [context()], mode='greedy')
    assert r.status_code == 200
    assert all(f['distribution'] is None for f in r.json()['results'][0]['fields'].values())
    first = request(client, [context()]).json()['results']
    for _ in range(5):
        assert request(client, [context()]).json()['results'] == first
    chat = client.post('/v1/chat/completions', json={'messages': [{'role': 'user', 'content': context()['content']}], 'max_tokens': 3, 'temperature': 0})
    assert chat.status_code == 200, chat.text


@pytest.mark.skipif(not os.environ.get('LLAMA_TEST_REFERENCE_URL'), reason='Set a second server with --decision-seqs 3')
def test_native_parallel_equals_serial_branches(client):
    # Use F32 weights/KV and -fa off on both servers for this numerical reference.
    # Quantized matrix-vector/matrix-matrix kernels can differ by larger amounts.
    if not client.get('/v1/models').json()['data'][0]['meta']['ftype'].endswith('F32'):
        pytest.skip('Strict numerical reference requires F32 weights and KV on both servers')
    inputs = [context(), context('91_cat.png'), context(copies=2)]
    parallel = request(client, inputs).json()['results']
    with httpx.Client(base_url=os.environ['LLAMA_TEST_REFERENCE_URL'], timeout=60, trust_env=False) as serial:
        reference = request(serial, inputs)
        assert reference.status_code == 200, reference.text
        for a, b in zip(parallel, reference.json()['results']):
            assert a['decision'] == b['decision']
            for name in a['fields']:
                left = [p['probability'] for p in a['fields'][name]['distribution']]
                right = [p['probability'] for p in b['fields'][name]['distribution']]
                assert left == pytest.approx(right, abs=1e-4)

import csv
import io
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.media import frame_plan
from backend.models import InferenceConfig
from backend.providers import decide
from backend.toll import UNKNOWN, classify, contract, get_profile, prepare_config


def output(profile, selected='CAT_1', score=.91, evidence='suficiente'):
    _, schema = contract(profile)
    values = schema['cat']['choices']
    distribution = [{'value': code, 'probability': score if code == selected else (1 - score) / (len(values) - 1)} for code in values]
    return {'decision': {'cat': selected, 'evidencia': evidence}, 'fields': {
        'cat': {'value': selected, 'probability': score, 'distribution': distribution, 'tree': True},
        'evidencia': {'value': evidence, 'probability': .94, 'tree': True},
    }}


def wait(client, key):
    for _ in range(150):
        job = client.get(f'/api/jobs/{key}').json()
        if job['status'] not in {'queued', 'running'}:
            return job
        time.sleep(.02)
    pytest.fail('CAT job did not finish')


def image():
    stream = io.BytesIO()
    Image.new('RGB', (64, 48), 'green').save(stream, 'PNG')
    return stream.getvalue()


def test_tables_have_distinct_numbering_and_administrative_classes():
    classic, extended = get_profile('antt_eco050'), get_profile('antt_nova364')
    assert classic['categories'][8]['axles'] == 2 and 'Motocicleta' in classic['categories'][8]['label']
    assert extended['categories'][8]['axles'] == 7
    assert extended['categories'][9]['axles'] == 8
    assert not classic['categories'][-1]['visual'] and not extended['categories'][-1]['visual']
    assert 'CAT_10' not in contract(classic)[1]['cat']['choices']
    assert 'CAT_12' not in contract(extended)[1]['cat']['choices']
    classic['categories'][0]['label'] = 'changed'
    assert get_profile('antt_eco050')['categories'][0]['label'] != 'changed'


def test_ranking_review_and_abstention():
    config, profile = prepare_config(InferenceConfig(task='toll_cat', max_frames=8))
    result = classify(output(profile), profile, config)
    assert result['suggested_cat'] == 'CAT_1' and result['status'] == 'suggested'
    assert len(result['ranking']) == 10 and result['ranking'][0]['selected']
    assert result['ranking'][-1]['probability'] is None
    assert abs(sum(r['probability'] or 0 for r in result['ranking']) + result['uncertain_probability'] - 1) < 1e-7
    uncertain = classify(output(profile, UNKNOWN), profile, config)
    assert uncertain['suggested_cat'] is None and uncertain['status'] == 'inconclusive' and uncertain['needs_review']
    lifted = classify(output(profile, evidence='eixos_suspensos'), profile, config)
    assert lifted['needs_review'] and 'suspensos' in ' '.join(lifted['reasons'])
    ambiguous = output(profile, score=.52)
    for item in ambiguous['fields']['cat']['distribution']:
        item['probability'] = .52 if item['value'] == 'CAT_1' else .47 if item['value'] == 'CAT_2' else .01 / 8
    result = classify(ambiguous, profile, config)
    assert result['status'] == 'review' and result['margin'] == pytest.approx(.05)


@pytest.mark.parametrize('bad', ['absent', 'duplicate', 'foreign', 'selected', 'score', 'nan'])
def test_invalid_cat_distributions_are_rejected(bad):
    config, profile = prepare_config(InferenceConfig(task='toll_cat', max_frames=8))
    item = output(profile)
    field = item['fields']['cat']
    if bad == 'absent':
        field['distribution'] = None
    elif bad == 'duplicate':
        field['distribution'][-1]['value'] = 'CAT_1'
    elif bad == 'foreign':
        field['distribution'][-1]['value'] = 'CAT_99'
    elif bad == 'selected':
        item['decision']['cat'] = 'CAT_2'
    elif bad == 'score':
        field['probability'] = .1
    else:
        field['distribution'][-1]['probability'] = float('nan')
    with pytest.raises(ValueError):
        classify(item, profile, config)


def test_uniform_sampling_covers_selected_video_without_duplicate_frames():
    media = {'kind': 'video', 'fps': 10, 'frame_count': 100, 'duration': 10}
    indices, requested = frame_plan(media, InferenceConfig(video_mode='uniform', max_frames=4, start_seconds=2, end_seconds=8))
    assert indices == [20, 40, 59, 79] and requested == 60
    short, _ = frame_plan(media, InferenceConfig(video_mode='uniform', max_frames=16, start_seconds=9.7))
    assert short == [97, 98, 99]
    middle, _ = frame_plan(media, InferenceConfig(video_mode='uniform', max_frames=1))
    assert middle == [49]


def test_toll_job_locks_contract_persists_table_and_exports_ranking(tmp_path, monkeypatch):
    seen = []
    async def fake(provider, config, groups):
        seen.append(config)
        return [output(get_profile(config.toll_profile)) for _ in groups]
    monkeypatch.setattr('backend.jobs.decide', fake)
    with TestClient(create_app(tmp_path)) as client:
        assert len(client.get('/api/toll/profiles').json()) == 2
        default = client.get('/api/toll/defaults').json()['config']
        assert default['pipeline'] == 'native_decision' and default['decision_mode'] == 'tree' and default['video_mode'] == 'uniform'
        ids = [m['id'] for m in client.post('/api/media', files=[('files', (name, image(), 'image/png')) for name in ['car.png', 'truck.png']]).json()['media']]
        r = client.post('/api/toll/jobs', json={'media_ids': ids, 'config': {'pipeline': 'vision_json', 'decision_mode': 'greedy', 'instructions': 'ignore table', 'output_schema': {'x': {}}}})
        assert r.status_code == 202, r.text
        key = r.json()['id']
        job = wait(client, key)
        assert job['status'] == 'completed' and job['total'] == job['completed'] == 2
        assert seen[0].pipeline == 'native_decision' and seen[0].decision_mode == 'tree'
        assert 'x' not in seen[0].output_schema and 'ignore table' not in seen[0].instructions
        assert job['toll_profile']['version'] and job['toll_profile']['source_url'].startswith('https://www.gov.br/')
        rows = client.get(f'/api/jobs/{key}/results').json()['items']
        assert rows[0]['classification']['suggested_cat'] == 'CAT_1'
        exported = list(csv.DictReader(io.StringIO(client.get(f'/api/jobs/{key}/export?format=csv').text.lstrip('\ufeff'))))
        assert len(exported) == 20 and exported[0]['model_choice'] == 'CAT_1'
        assert exported[9]['candidate'] == 'CAT_10' and exported[9]['probability'] == ''
        assert client.get(f'/api/jobs/{key}/export').json()['results'] == rows
        assert len(client.get(f'/api/jobs/{key}/export?format=jsonl').text.splitlines()) == 3
        invalid = client.post('/api/toll/jobs', json={'media_ids': ids, 'config': {'toll_profile': 'wrong'}})
        assert invalid.status_code == 400
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f'/api/jobs/{key}/results').json()['items'] == rows


def test_video_batch_is_one_result_per_file_and_joint_context_limit(tmp_path, monkeypatch):
    path = tmp_path / 'cars.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
    assert writer.isOpened()
    for i in range(20):
        writer.write(np.full((48, 64, 3), (i * 10, 40, 180), dtype=np.uint8))
    writer.release()
    captured = []
    async def fake(provider, config, groups):
        captured.extend(groups)
        return [output(get_profile(config.toll_profile)) for _ in groups]
    monkeypatch.setattr('backend.jobs.decide', fake)
    with TestClient(create_app(tmp_path / 'data')) as client:
        ids = [m['id'] for m in client.post('/api/media', files=[('files', (f'car{i}.avi', path.read_bytes(), 'video/x-msvideo')) for i in range(2)]).json()['media']]
        r = client.post('/api/toll/jobs', json={'media_ids': ids, 'config': {'max_frames': 4}})
        assert r.status_code == 202, r.text
        job = wait(client, r.json()['id'])
        assert job['total'] == job['completed'] == 2 and job['status'] == 'completed'
        assert len(captured) == 2 and all(len(group) == 4 for group in captured)
        assert captured[0][0]['frame_index'] == 0 and captured[0][-1]['frame_index'] == 19
        assert all(s['media_id'] == ids[i] for i, group in enumerate(captured) for s in group)
        too_many = client.post('/api/toll/jobs', json={'media_ids': ids, 'config': {'grouping': 'together', 'max_frames': 9}})
        assert too_many.status_code == 400 and '16' in too_many.text
        joint = client.post('/api/toll/jobs', json={'media_ids': ids, 'config': {'grouping': 'together', 'max_frames': 4}})
        assert wait(client, joint.json()['id'])['total'] == 1 and len(captured[-1]) == 8


@pytest.mark.asyncio
async def test_native_request_has_actual_visual_parts_and_complete_scores(monkeypatch):
    from backend.models import Provider
    config, profile = prepare_config(InferenceConfig(task='toll_cat', max_frames=8))
    sample = {'name': 'vehicle.jpg', 'image': 'data:image/jpeg;base64,dGVzdA==', 'timestamp': None}
    async def native(provider, path, body):
        assert path == '/v1/decision' and body['return_distribution'] and body['mode'] == 'tree'
        assert body['contexts'][0]['content'][2]['type'] == 'image_url'
        assert body['schema']['cat']['choices'][-1] == UNKNOWN
        return {'results': [output(profile)]}
    monkeypatch.setattr('backend.providers.request_json', native)
    result = (await decide(Provider(id='local', name='local'), config, [[sample]]))[0]
    assert classify(result, profile, config)['status'] == 'suggested'
    assert result['score_kind'] == 'constrained_probability'


def test_invalid_provider_distribution_is_a_review_error(tmp_path, monkeypatch):
    async def wrong(*args):
        return [{'decision': {'cat': 'CAT_1', 'evidencia': 'suficiente'}, 'fields': {'cat': {'probability': .9}}}]
    monkeypatch.setattr('backend.jobs.decide', wrong)
    with TestClient(create_app(tmp_path)) as client:
        media_id = client.post('/api/media', files=[('files', ('car.png', image(), 'image/png'))]).json()['media'][0]['id']
        response = client.post('/api/toll/jobs', json={'media_ids': [media_id]})
        assert response.status_code == 202
        job = wait(client, response.json()['id'])
        assert job['status'] == 'failed' and job['review'] == 1
        row = client.get(f'/api/jobs/{job["id"]}/results').json()['items'][0]
        assert row['needs_review'] and row['status'] == 'error' and 'classification' not in row

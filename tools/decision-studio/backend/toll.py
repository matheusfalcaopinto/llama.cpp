from __future__ import annotations

import copy
import math

VERSION = '2026-09-30.1'
DEFAULT_PROFILE = 'antt_eco050'
UNKNOWN = 'INDETERMINADO'


def category(number, label, axles, wheels, multiplier, visual=True):
    return {'code': f'CAT_{number}', 'number': number, 'label': label, 'axles': axles,
            'wheels': wheels, 'multiplier': multiplier, 'visual': visual}


COMMON = [
    category(1, 'Automóvel, caminhonete ou furgão', 2, 'simples', 1),
    category(2, 'Caminhão leve, ônibus, caminhão-trator ou furgão', 2, 'dupla', 2),
    category(3, 'Automóvel ou caminhonete com semirreboque', 3, 'simples', 1.5),
    category(4, 'Caminhão, caminhão-trator ou ônibus', 3, 'dupla', 3),
    category(5, 'Automóvel ou caminhonete com reboque', 4, 'simples', 2),
    category(6, 'Caminhão com reboque ou caminhão-trator com semirreboque', 4, 'dupla', 4),
    category(7, 'Caminhão com reboque ou caminhão-trator com semirreboque', 5, 'dupla', 5),
    category(8, 'Caminhão com reboque ou caminhão-trator com semirreboque', 6, 'dupla', 6),
]
PROFILES = {
    'antt_eco050': {
        'id': 'antt_eco050', 'name': 'ANTT - Ecovias Minas Goiás (clássica)',
        'version': VERSION, 'verified_at': '2026-09-30', 'source_updated_at': '2026-08-28',
        'source_url': 'https://www.gov.br/antt/pt-br/assuntos/rodovias/concessionarias/lista-de-concessoes/eco050/tarifas-de-pedagio',
        'categories': COMMON + [
            category(9, 'Motocicleta, motoneta ou bicicleta motorizada', 2, 'simples', .5),
            category(10, 'Veículo oficial ou do Corpo Diplomático', None, None, None, False),
        ],
    },
    'antt_nova364': {
        'id': 'antt_nova364', 'name': 'ANTT - Nova 364 (até 8 eixos)',
        'version': VERSION, 'verified_at': '2026-09-30', 'source_updated_at': '2026-01-15',
        'source_url': 'https://www.gov.br/antt/pt-br/assuntos/rodovias/concessionarias/lista-de-concessoes/nova-364/tarifas-de-pedagio',
        'categories': COMMON + [
            category(9, 'Caminhão com reboque ou caminhão-trator com semirreboque', 7, 'dupla', 7),
            category(10, 'Caminhão com reboque ou caminhão-trator com semirreboque', 8, 'dupla', 8),
            category(11, 'Motocicleta, motoneta, triciclo ou bicicleta motorizada', None, None, None),
            category(12, 'Ambulância, veículo oficial ou do Corpo Diplomático', None, None, None, False),
        ],
    },
}
EVIDENCE = {
    'suficiente': 'Evidência visual suficiente segundo o modelo.',
    'eixos_ocultos': 'Eixos ou rodagem não estão suficientemente visíveis.',
    'multiplos_veiculos': 'Mais de um veículo nas mídias; separe o veículo de interesse.',
    'sem_veiculo': 'O modelo não identificou um veículo nas mídias.',
    'eixos_suspensos': 'Possíveis eixos suspensos; a categoria tarifável exige revisão.',
    'fora_da_tabela': 'Veículo ou configuração fora das categorias visuais desta tabela.',
}


def get_profile(key):
    if key not in PROFILES:
        raise ValueError('Tabela CAT desconhecida. Selecione um dos perfis disponíveis.')
    return copy.deepcopy(PROFILES[key])


def contract(profile):
    lines = []
    for c in profile['categories']:
        if c['visual']:
            attributes = f"{c['axles']} eixos, rodagem {c['wheels']}" if c['axles'] is not None else 'categoria por tipo de veículo'
            lines.append(f"{c['code']}: {c['label']}; {attributes}.")
    table = '\n'.join(lines)
    instructions = (
        'Classifique um único veículo para uma sugestão de categoria de pedágio no Brasil. '
        'Use exclusivamente as imagens e a tabela abaixo. As imagens/quadros de cada contexto devem mostrar o mesmo veículo. '
        'Não use nomes de arquivos como evidência. Conte eixos, não rodas visíveis; não some o mesmo eixo entre vistas. '
        'Rodagem dupla significa pneus lado a lado no eixo, não dois eixos. Considere reboques e semirreboques. '
        'Não adivinhe eixos ou rodagem ocultos. Se não houver veículo, houver veículos diferentes, não for possível '
        'determinar a categoria ou a configuração estiver fora da tabela, escolha INDETERMINADO. '
        'Eixos possivelmente suspensos exigem revisão: não determine eixos tarifáveis nem condição de carga por aparência. '
        'Não infira isenção, condição oficial/diplomática, valor em reais, descontos ou tarifa final por imagem. '
        'Quando uma categoria depende de comprovação administrativa, use INDETERMINADO. '
        f"Tabela exclusiva: {profile['name']} (versão {profile['version']}).\n{table}"
    )
    schema = {
        'cat': {'type': 'enum', 'choices': [c['code'] for c in profile['categories'] if c['visual']] + [UNKNOWN],
                'description': 'Qual CAT da tabela corresponde ao único veículo, com base em tipo, eixos e rodagem? '
                               'Escolha INDETERMINADO se a evidência for insuficiente ou houver mais de um veículo.\n' + table},
        'evidencia': {'type': 'enum', 'choices': list(EVIDENCE),
                      'description': 'Qual condição melhor descreve a evidência visual para categorizar este veículo? '
                                     + ' '.join(f'{k}: {v}' for k, v in EVIDENCE.items())},
    }
    return instructions, schema


def prepare_config(config):
    profile = get_profile(config.toll_profile)
    if config.max_frames > 16:
        raise ValueError('Para CAT, use até 16 quadros por vídeo. Cada arquivo é um veículo; selecione o trecho relevante.')
    instructions, schema = contract(profile)
    return config.model_copy(update={'task': 'toll_cat', 'pipeline': 'native_decision',
                                     'decision_mode': 'tree', 'tree_max': 128,
                                     'instructions': instructions, 'output_schema': schema}), profile


def classify(output, profile, config):
    fields = output.get('fields', {})
    f = fields.get('cat', {})
    distribution = f.get('distribution')
    candidates = {c['code'] for c in profile['categories'] if c['visual']} | {UNKNOWN}
    if not isinstance(distribution, list) or len(distribution) != len(candidates):
        raise ValueError('O servidor não retornou a distribuição CAT completa. Use decisão tree neste fork.')
    scores = {}
    for item in distribution:
        if not isinstance(item, dict):
            raise ValueError('Distribuição CAT inválida.')
        code, p = item.get('value'), item.get('probability')
        if not isinstance(code, str) or code not in candidates or code in scores:
            raise ValueError('Distribuição CAT com categorias ausentes, desconhecidas ou repetidas.')
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Score CAT inválido.')
        scores[code] = float(p)
    if not math.isclose(sum(scores.values()), 1, abs_tol=1e-4):
        raise ValueError('Distribuição CAT não normalizada.')
    selected = output.get('decision', {}).get('cat')
    best = max(scores.values())
    if selected not in scores or not math.isclose(scores[selected], best, abs_tol=1e-6):
        raise ValueError('A categoria escolhida pelo servidor diverge da maior probabilidade.')
    if f.get('probability') is None or not math.isclose(f['probability'], scores[selected], abs_tol=1e-4):
        raise ValueError('Score da categoria escolhida diverge da distribuição.')
    evidence = output.get('decision', {}).get('evidencia')
    if evidence not in EVIDENCE:
        raise ValueError('O servidor não retornou a condição da evidência visual.')
    ranked = sorted(scores, key=lambda code: (-scores[code], code != selected, code))
    margin = scores[ranked[0]] - scores[ranked[1]]
    reasons = []
    if selected == UNKNOWN:
        reasons.append('O modelo escolheu INDETERMINADO; nenhum CAT foi atribuído.')
    if evidence != 'suficiente':
        reasons.append(EVIDENCE[evidence])
    if scores[selected] < config.review_threshold:
        reasons.append('Score da escolha abaixo do limiar de revisão.')
    if margin < config.review_margin:
        reasons.append('Diferença pequena entre as duas primeiras hipóteses.')
    evidence_p = fields.get('evidencia', {}).get('probability')
    if evidence_p is None or evidence_p < config.review_threshold:
        reasons.append('A avaliação da evidência também exige revisão.')
    categories = {c['code']: c for c in profile['categories']}
    ranking = [{**categories[code], 'probability': scores[code], 'selected': code == selected}
               for code in ranked if code != UNKNOWN]
    ranking += [{**c, 'probability': None, 'selected': False} for c in profile['categories'] if not c['visual']]
    return {'profile_id': profile['id'], 'profile_name': profile['name'], 'profile_version': profile['version'],
            'selected': selected, 'suggested_cat': None if selected == UNKNOWN else selected,
            'selected_probability': scores[selected], 'uncertain_probability': scores[UNKNOWN],
            'margin': margin, 'evidence': evidence, 'ranking': ranking,
            'status': 'inconclusive' if selected == UNKNOWN else 'review' if reasons else 'suggested',
            'needs_review': bool(reasons), 'reasons': reasons,
            'score_kind': 'constrained_probability'}

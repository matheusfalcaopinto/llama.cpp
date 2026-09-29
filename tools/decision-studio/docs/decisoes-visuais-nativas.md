# Registro de arquitetura: decisões visuais nativas em parallel-decision

Análise estática em 2026-09-29. Repositório: https://github.com/thecodacus/llama.cpp/tree/parallel-decision

Commit examinado: `ad129b08d9f134cd298d1f8a85efc52b1b66e18e`.

**Atualização de implementação, 2026-09-29:** o caminho nativo e o aplicativo foram implementados na branch `codex/decision-vision`, compilados no Windows e testados com o fixture visual tinygemma3. O contrato atual está no [README](../README.md), e a matriz de evidências e limitações em [VALIDATION.md](VALIDATION.md).

O restante deste documento preserva a análise estática inicial e seus critérios de aceitação, inclusive itens ainda não cobertos pela matriz de testes. Não deve ser interpretado como uma declaração de suporte validado a todas as arquiteturas. Na implementação, a capacidade se chama `data[].decision.vision`; os testes nativos estão em `tools/decision-studio/tests/test_native.py`.

## Resultado esperado

Executar decisões condicionadas diretamente aos embeddings da imagem de um modelo multimodal compatível, usando o mecanismo de alternativas finitas da branch. O fluxo seria:

`imagem + texto + schema -> template multimodal -> encoder/projector -> prefill no modelo -> ramificações por campo -> logits -> probabilidades e valores tipados`

Não há necessidade conceitual de uma descrição textual intermediária. É necessário um modelo com capacidade visual e seu projector compatível; esta integração não acrescenta visão a um modelo exclusivamente textual. A princípio não requer treinamento nem mudanças no formato GGUF ou nos kernels do GGML, desde que o modelo e seu caminho multimodal já sejam suportados. Isso é uma conclusão de arquitetura, ainda não comprovada por execução.

## Evidência no código atual

| Local | Comportamento observado |
|---|---|
| `tools/server/server-context.cpp`, `handle_decision()` | Aceita `contexts` com 1–256 strings não vazias, renderiza texto e chama `decide_batch()`. |
| `tools/parallel-decision/decision-engine.h/.cpp` | O motor aceita strings, converte-as em `llama_token` e faz o prefill com `decode_parts()`. |
| `tools/parallel-decision/decision-engine.cpp`, `score_branches()` | Copia o estado da sequência base para sequências de alternativas usando `llama_memory_seq_cp()`. |
| `tools/server/server-common.cpp` | O parser de chat já extrai `image_url`, aplica os templates e prepara mídia; `process_mtmd_prompt()` produz chunks multimodais. |
| `tools/server/server-context.cpp`, `process_mtmd_chunk()` | Já usa encoding de mídia e `mtmd_helper_decode_image_chunk()` no contexto do modelo. |
| `tools/mtmd/mtmd-helper.h/.cpp` | Disponibiliza avaliação de chunks, posições multimodais e tratamento de atenção não causal durante o processamento de imagens. |
| `tools/server/CMakeLists.txt` | `server-context` já depende tanto de `mtmd` quanto de `llama-decision`. |

Referências fixas: [motor](https://github.com/thecodacus/llama.cpp/blob/ad129b08d9f134cd298d1f8a85efc52b1b66e18e/tools/parallel-decision/decision-engine.cpp), [contrato do motor](https://github.com/thecodacus/llama.cpp/blob/ad129b08d9f134cd298d1f8a85efc52b1b66e18e/tools/parallel-decision/decision-engine.h), [servidor](https://github.com/thecodacus/llama.cpp/blob/ad129b08d9f134cd298d1f8a85efc52b1b66e18e/tools/server/server-context.cpp), [preparação de mídia](https://github.com/thecodacus/llama.cpp/blob/ad129b08d9f134cd298d1f8a85efc52b1b66e18e/tools/server/server-common.cpp), [helpers multimodais](https://github.com/thecodacus/llama.cpp/blob/ad129b08d9f134cd298d1f8a85efc52b1b66e18e/tools/mtmd/mtmd-helper.h).

## 1. Estender o contrato de entrada

Preservar `contexts: string[]` e aceitar também objetos de contexto com conteúdo multimodal. Um objeto representa uma decisão sobre uma ou mais imagens; vários objetos representam exemplos independentes.

Exemplo de API proposta, ainda não suportada:

```json
{
  "model": "meu-modelo-visual",
  "instructions": "Avalie apenas o que está visível na imagem.",
  "contexts": [
    {
      "content": [
        {"type": "text", "text": "Inspecione esta peça impressa em 3D."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
      ]
    }
  ],
  "schema": {
    "defeito_visivel": {"type": "boolean", "description": "Há um defeito visível?"},
    "qualidade": {
      "type": "integer", "minimum": 0, "maximum": 10,
      "aggregate": "mean", "description": "Qualidade visual: 0 péssima, 10 excelente."
    }
  },
  "mode": "tree",
  "return_distribution": true
}
```

Usar data URLs na primeira entrega mantém o contrato simples. Se URLs remotas forem expostas, reaproveitar as políticas de acesso a mídia do servidor e definir limites de download. Validar o número de imagens, bytes, dimensões, tipos aceitos, memória e capacidade visual antes do encoding. A opção `return_distribution` acima também é uma proposta.

Arquivos prováveis: `server-context.cpp`, `server-common.cpp/.h` e possivelmente `server-task.h`, caso a tarefa passe a transportar entradas preparadas e buffers em vez de todo o JSON original.

## 2. Reaproveitar o template e a preparação multimodal

Converter cada contexto em mensagem de usuário com texto e marcadores de imagem. Colocar o catálogo de campos e as instruções na mensagem de sistema. Aplicar o template real do modelo, com geração de raciocínio desativada, e preservar a abertura da resposta usada pelo scorer.

O renderizador atual de decisões usa uma sentinela em uma mensagem textual e substitui seu conteúdo posteriormente. Essa estratégia não deve ser estendida simplesmente concatenando base64 ou marcadores: os modelos podem precisar de tratamento específico no template para conteúdo visual.

Reaproveitar ou extrair a parte necessária de `oaicompat_chat_params_parse()` e `process_mtmd_prompt()`. O parser completo de chat também cuida de ferramentas, gramáticas e parâmetros de geração; o endpoint de decisão precisa apenas de sua normalização de conteúdo e template.

## 3. Separar prefill e scoring no motor

Adicionar uma entrada abstrata preparada ou um callback de prefill, mantendo o método textual existente como adaptador. O motor continua responsável pela alocação e liberação de suas sequências; o adaptador multimodal recebe a sequência reservada, faz seu prefill e devolve a posição seguinte e as métricas.

Esboço conceitual, não API existente:

```cpp
struct prefill_result {
    llama_pos next_pos;
    size_t text_tokens;
    size_t image_tokens;
};

// Executado no contexto/thread de inferência autorizado pelo servidor.
using prefill_fn = std::function<prefill_result(llama_seq_id trunk)>;
```

Este desenho permite manter `llama-decision` sem dependência direta de `mtmd`. O servidor, que já depende dos dois, fornece o adaptador. Alternativamente, o motor poderia depender diretamente de `mtmd`, com mudança no CMake e impacto também no executável textual.

Para cada contexto: preparar texto e imagens na sequência base, garantir término do prefill, então copiar essa sequência para as alternativas de cada campo. Não executar novamente o encoder de visão para cada pergunta.

Os helpers existentes oferecem um primeiro caminho funcional. Um estágio posterior pode reaproveitar `mtmd_batch_*` para agrupar encoding de imagens. Não executar chamadas simultâneas sobre o mesmo `mtmd_context`/`llama_context`: os helpers de avaliação não são thread-safe.

## 4. Corrigir posições, cache e limites

Hoje `pos0` das alternativas é calculado como `shared.size() + prefixes[i].size()`. Substituir pela posição efetiva do prefill multimodal. Os helpers já distinguem número de tokens de número de posições, necessário em M-RoPE. Preservar também o tratamento de posições visuais e da atenção não causal durante os chunks de imagem.

A primeira versão pode processar o prompt multimodal completo sem cache entre requisições e manter o compartilhamento entre campos da mesma requisição. Depois, habilitar cache apenas do prefixo textual comprovadamente comum. Cache visual posterior deve incluir identidade do modelo/projector, conteúdo da imagem, parâmetros de pré-processamento e template; contar apenas tokens não identifica uma imagem.

Dimensionar separadamente: quantidade de sequências, tokens/embeddings visuais, posições, espaço do cache e linhas de batch. Ajustar os agrupamentos quando a combinação de imagens e alternativas não couber. Fazer rollback das sequências reservadas em erro/cancelamento sem limpar slots de chat.

O handler atual executa a decisão dentro do processamento de tarefas do servidor. Imagens tornam essa operação mais longa: incluir checagens cooperativas de cancelamento entre chunks e grupos. Para a primeira versão, lotes pequenos e limites explícitos; processamento incremental no scheduler é uma otimização posterior para coexistência responsiva com chat.

## 5. Manter decisões tipadas e melhorar os scores

O esquema atual já suporta booleanos, enums e números em um conjunto finito de até 255 valores. Uma escala inteira de 0 a 10, por exemplo, não exige um novo tipo de modelo: são 11 alternativas avaliadas com a imagem no contexto.

O modo `tree` calcula a distribuição completa das alternativas. `greedy` percorre apenas o caminho escolhido, portanto não permite exportar a mesma distribuição completa. Para scores/distribuições completos, exigir `tree` ou verificar `tree: true` no campo; `auto` pode selecionar greedy para campos maiores.

`field_result.probs` já existe internamente, mas `assemble()` não exporta a distribuição completa. Acrescentar opcionalmente uma lista de `{value, probability}`, mantendo os campos existentes. Retornar a média esperada em campo separado se desejada: nesta revisão, `aggregate: mean` escolhe o valor permitido mais próximo da média, e `probability` é a probabilidade desse valor escolhido, não a média nem uma confiança calibrada.

Adicionar metadados propostos para separar quantidade de imagens, tokens visuais, tempo do encoder, prefill do decoder e scoring. Expor capacidade `decision_image` somente após o servidor confirmar caminho visual, projector e configuração de decisões.

Essas probabilidades são relativas às alternativas e ao procedimento de scoring restrito. Não são automaticamente probabilidades calibradas de um defeito real. Para uso quantitativo, medir acurácia/calibração em imagens rotuladas da aplicação.

## 6. Validar antes de integrar ao cliente

Critérios de aceitação:

- Requisições textuais antigas continuam funcionando e preservam resultados dentro da tolerância numérica estabelecida.
- Scoring paralelo e uma referência sequencial usam exatamente o mesmo prompt, imagens, posições e normalização restrita e concordam dentro da tolerância.
- Imagens controladas com conteúdo distinto alteram os logits pertinentes; apenas aceitar o payload não comprova que a imagem foi usada.
- Imagens idênticas em lote e isoladamente produzem resultados equivalentes, sem contaminação entre sequências.
- Casos com várias imagens, tamanhos diferentes, crops e M-RoPE têm posições corretas.
- Modelos sem visão, projector ausente, mídia corrompida, falta de cache e excesso de entrada falham com erro útil.
- Cancelamento e erros liberam recursos e não quebram a requisição seguinte nem slots de chat.
- Distribuições de tree somam 1; média, valor permitido escolhido, intervalo e probabilidade mantêm semânticas distintas.
- Medir custo de encoder, prefill e scoring separadamente. Não prometer uma única passagem total: encoder, prefill e grupos de alternativas envolvem operações distintas.

Criar `test_decision_vision.py` ao lado de `tools/server/tests/unit/test_vision_api.py`, além de testes do motor para posições/limites e regressão textual. Começar com uma família visual comprovadamente suportada; ampliar a matriz para modelos com M-RoPE, atenção por janela e estados recorrentes/híbridos.

## Vídeos e sequência de entrega

Primeiro, uma imagem por contexto; depois lotes de contextos e múltiplas imagens por contexto. Para vídeo, o cliente pode amostrar quadros e enviar um contexto por quadro, produzindo decisões com timestamps. Para decisões temporais, enviar pequenos grupos de quadros com timestamps no mesmo contexto e validar se o modelo realmente compreende a relação temporal. Acumular quadros não cria automaticamente rastreamento ou memória temporal.

A biblioteca já tem helpers de vídeo, mas sua documentação condiciona o suporte à compilação e registra limitações por modelo. A primeira integração não precisa depender do transporte de um vídeo inteiro ao servidor.

Escopo recomendado: mudanças no contrato HTTP, preparação do prompt, interface de prefill, posições/cache e resposta/testes. O reaproveitamento do encoder e do scorer reduz o trabalho; a maior incerteza está na correção e compatibilidade do estado multimodal ao ramificar sequências. Classificação qualitativa: implementação de porte médio, com validação de porte maior se abranger muitas famílias de modelos.

# CAT Studio

Aplicação local/LAN dedicada a sugerir categorias de veículos para pedágio a partir de uma imagem, um vídeo ou lotes de mídias. Branch `codex/toll-cat` do [fork llama.cpp](https://github.com/matheusfalcaopinto/llama.cpp/tree/codex/toll-cat), derivada de `codex/decision-vision`.

A saída mostra a escolha do modelo, o ranking de todos os CAT visuais com seus scores, a hipótese indeterminado e motivos para revisão. Os scores são probabilidades restritas às opções da tabela, não acurácia calibrada. A aplicação não calcula cobrança.

## Iniciar

No Windows, nesta pasta ou em `tools/decision-studio` do fork:

```powershell
.\start.bat
```

Na primeira execução, instale [uv](https://docs.astral.sh/uv/getting-started/installation/) e Node.js 22+. O launcher instala as dependências travadas e compila a interface. Depois de atualizar o código, use `start.bat -Build` e reinicie o processo com `stop.bat` antes de iniciar novamente.

- Local: `http://127.0.0.1:8765`.
- LAN: `http://IP-DESTA-MAQUINA:8765`; o launcher mostra os IPs atuais.
- Sem navegador: `start.bat -NoBrowser`.
- Outra porta: `start.bat -Port 8766`.
- Apenas localhost: `start.bat -Bind 127.0.0.1`.
- Parar o processo registrado: `stop.bat`.

O processo fica em segundo plano. Logs em `logs/`; biblioteca e histórico em `data/`. Todos os clientes usam a mesma biblioteca e histórico. A aplicação não tem login e se destina a LAN confiável; não a exponha diretamente à Internet. O launcher não modifica o firewall.

Linux/macOS:

```bash
uv sync --frozen
npm ci
npm run build
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8765 --workers 1
```

## Servidor e modelo

Configure em Provedores a URL, chave opcional e timeout do llama.cpp com um modelo GGUF de visão e mmproj compatível. O modelo pode ficar vazio para usar o carregado no servidor. O aplicativo não baixa nem treina um modelo classificador de veículos.

```bash
git clone --branch codex/toll-cat --single-branch https://github.com/matheusfalcaopinto/llama.cpp.git
cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF
cmake --build build --config Release --target llama-server -j 4
./build/bin/llama-server -m model-vision.gguf --mmproj mmproj.gguf --decision-seqs 16 --parallel 1 -c 16384 --host 127.0.0.1 --port 8080
```

Ajuste memória, contexto e sequências ao modelo. CUDA pode ser compilado com `-DGGML_CUDA=ON`; o build testado aqui foi CPU Windows. O servidor da branch `codex/decision-vision` também é compatível. Esta versão utiliza a API visual nativa existente: as imagens entram no modelo e o contexto visual é compartilhado entre os campos `cat` e `evidencia`.

## Tabelas CAT

Não existe numeração única para todas as concessões. Dois perfis versionados foram conferidos em 30/09/2026:

- **ANTT - Ecovias Minas Goiás (clássica)**, padrão inicial: CAT 1 a 8 por tipo/eixos/rodagem, CAT 9 motocicletas; CAT 10 depende de condição administrativa. [Tabela oficial](https://www.gov.br/antt/pt-br/assuntos/rodovias/concessionarias/lista-de-concessoes/eco050/tarifas-de-pedagio).
- **ANTT - Nova 364 (até 8 eixos)**: CAT 9 e 10 correspondem a veículos de 7 e 8 eixos; CAT 11 motocicletas/triciclos; CAT 12 depende de condição administrativa. [Tabela oficial](https://www.gov.br/antt/pt-br/assuntos/rodovias/concessionarias/lista-de-concessoes/nova-364/tarifas-de-pedagio).

A tabela inteira, sua fonte e versão ficam salvas com a execução. As categorias administrativas aparecem na lista sem score visual; não integram a distribuição. A distribuição soma 1 entre os CAT visuais e `INDETERMINADO`. Não presumimos isenção, carga, eixos tarifáveis ou descontos por aparência. Eixos possivelmente suspensos sinalizam revisão. Para outra concessionária, valide e adicione um perfil em `backend/toll.py` antes de usar sua numeração.

## Fluxo

1. Importe uma imagem, vídeo, lote misto ou diretório.
2. Escolha a tabela e o provedor/modelo.
3. Selecione **um veículo por arquivo** (padrão), **mesmo veículo em todas as mídias** ou **um veículo por pasta**. Em conjunto/pasta, todas as mídias devem mostrar o mesmo veículo.
4. Para vídeo, os quadros são distribuídos no trecho inteiro por padrão: 8 quadros, até 16. É possível selecionar início/fim ou amostrar por intervalo. Um vídeo produz um resultado com seus quadros analisados juntos.
5. Execute. Compare todos os CAT e a hipótese indeterminado. O maior score destaca a escolha do modelo; score baixo, pequena diferença entre hipóteses e evidência insuficiente sinalizam revisão.
6. Consulte timestamps, previews, dados originais e configuração. Exporte JSON/JSONL ou CSV com uma linha por candidato de cada resultado.

Um contexto aceita até 16 imagens/quadros no total. Se um lote conjunto exceder isso, a execução é recusada com instrução para dividir a seleção. No modo individual, cada vídeo usa seu próprio contexto; arquivos distintos não são fundidos. Quadros por intervalo são extraídos a partir do início do trecho e podem atingir o limite antes do final; amostragem distribuída cobre os extremos do trecho.

Não há rastreamento ou segmentação automática de vários veículos em um vídeo. Recorte o veículo ou selecione o trecho de uma passagem; mídias ambíguas devem ser revisadas. Contagem de eixos/rodagem depende da visibilidade e da capacidade do modelo escolhido. O resultado é uma sugestão visual para avaliação, não validação de tarifação.

## API

- `GET /api/toll/profiles`: tabelas disponíveis e respectivas fontes.
- `GET /api/toll/defaults`: configuração inicial.
- `POST /api/media`: upload multipart, preservando o caminho relativo do diretório.
- `POST /api/toll/jobs`: `media_ids`, `name` opcional e `config` (perfil, modelo, agrupamento, vídeo e parâmetros de revisão).
- `GET /api/jobs/{id}/results`: resultados paginados, com `classification` e o ranking.
- `GET /api/jobs/{id}/export?format=json|jsonl|csv`: exportação.

O backend fixa instruções, schema e modo tree da tarefa CAT; o cliente não pode substituir a tarefa por geração JSON/greedy ou alterar categorias em uma execução CAT. Distribuições incompletas, repetidas ou inconsistentes produzem erro para revisão. A API genérica anterior continua disponível para compatibilidade, mas a interface deste branch usa apenas a tarefa CAT.

## Validação

Veja [a validação CAT](docs/CAT_VALIDATION.md). O modelo tinygemma3 usado para testes verifica a integração, não a qualidade de classificação de veículos. A acurácia para uma praça/modelo real ainda exige mídias representativas com CAT anotado por um especialista. A edição genérica continua na branch `codex/decision-vision`; sua documentação original está arquivada em [DECISION_STUDIO.md](docs/DECISION_STUDIO.md).

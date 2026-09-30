> Documentação arquivada da edição genérica, disponível no branch codex/decision-vision. Consulte ../README.md para a edição CAT.

# Decision Studio

Aplicação local/LAN para decisões visuais tipadas com a branch [`codex/decision-vision`](https://github.com/matheusfalcaopinto/llama.cpp/tree/codex/decision-vision) de llama.cpp. Interface em português, React/TypeScript, API FastAPI, histórico em SQLite e arquivos no disco local.

O modo **Decisão visual nativa** envia as imagens diretamente ao modelo de visão via `/v1/decision`, sem descrição textual intermediária. O modo opcional **JSON gerado pelo modelo** usa `/v1/chat/completions` com JSON Schema e não fornece probabilidades.

## Iniciar no Windows

Na pasta `tools/decision-studio` do fork (ou na cópia da aplicação neste workspace):

```powershell
.\start.bat
```

Na primeira execução, são necessários [uv](https://docs.astral.sh/uv/getting-started/installation/) e Node.js 22+ para instalar as dependências travadas em `uv.lock`/`package-lock.json` e compilar a interface. Depois, o launcher usa o ambiente `.venv` e o build local. O modelo é servido em outro processo, descrito abaixo.

- Local: `http://127.0.0.1:8765`.
- LAN: `http://IP-DESTA-MAQUINA:8765`; os endereços são mostrados pelo launcher.
- Sem abrir o navegador: `start.bat -NoBrowser`.
- Outra porta: `start.bat -Port 8766`.
- Somente localhost: `start.bat -Bind 127.0.0.1`.
- Recompilar após atualizar: `start.bat -Build`.
- Encerrar somente o processo registrado desta aplicação: `stop.bat`.

O processo fica ativo em segundo plano. Logs ficam em `logs/`. O launcher não altera regras do Firewall do Windows. Para acesso de outra máquina, a rede e o firewall precisam permitir a porta escolhida. A aplicação foi projetada para LAN confiável: não possui login nem isolamento entre usuários e não deve ser exposta diretamente à Internet. Todos os clientes acessam a mesma biblioteca e histórico.

Linux/macOS:

```bash
uv sync --frozen
npm ci
npm run build
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8765 --workers 1
```

## Servidor llama.cpp

Clone o fork e selecione a branch:

```bash
git clone --branch codex/decision-vision --single-branch https://github.com/matheusfalcaopinto/llama.cpp.git
cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF
cmake --build build --config Release --target llama-server llama-parallel-decision -j 4
```

Para CUDA, adicione `-DGGML_CUDA=ON` à configuração e use o toolchain CUDA/MSVC ou Linux compatível com seu ambiente. O build validado nesta entrega foi CPU no Windows; não foi validado CUDA.

Exemplo de servidor (ajuste os caminhos, contexto, sequências e GPU ao modelo/hardware):

```bash
./build/bin/llama-server -m model-vision.gguf --mmproj mmproj.gguf --decision-seqs 16 --parallel 1 -c 16384 --host 127.0.0.1 --port 8080
```

Em builds Windows com gerador multi-config, o executável pode ficar em `build/bin/Release/llama-server.exe`. `--decision-seqs` deve ser pelo menos 3; 16 é um ponto inicial, não uma exigência. Aumentar esse parâmetro pode custar muita memória em modelos com sliding-window/recurrent layers. Para servidor em outra máquina, faça-o escutar na interface LAN apropriada e configure o endereço no Studio.

O modelo **precisa ter visão e um projector compatível**. Um modelo textual não ganha visão com este patch. Jev e Laya não integram esta versão. O fato de uma arquitetura ser suportada pelo llama.cpp não constitui validação deste caminho de decisão com todos os seus modelos; consulte [a validação](VALIDATION.md).

Em **Provedores**, configure nome, URL, chave opcional e timeout. Teste a conexão e salve. O modelo pode ficar em branco para usar o carregado no servidor; a lista de modelos é consultada em `/v1/models`. O fork expõe `data[].decision.vision` para anunciar disponibilidade do endpoint visual.

## Fluxo de trabalho

1. Importe imagens, um lote, um diretório ou vídeos. Selecionar um diretório envia seus arquivos pelo navegador; não concede acesso geral ao disco do cliente.
2. Organize a ordem das entradas. A biblioteca preserva nome e caminho relativo.
3. Escolha agrupamento: **individual**, **conjunto** ou **por pasta**. Cada conjunto recebe um único resultado. Pastas distintas produzem grupos independentes.
4. Para vídeo, configure intervalo ou todos os quadros, início/fim, limite de amostragem e quadros por decisão. No modo individual, janelas consecutivas podem reunir até 16 quadros. A última janela pode ser menor. Em conjunto/por pasta, todos os quadros selecionados do grupo devem caber no limite de 16.
5. Configure campos booleanos, opções de texto ou números em uma grade finita, com uma descrição para cada pergunta. As estruturas são editáveis em formulário ou JSON.
6. Execute. A fila salva os resultados progressivamente; erros ficam registrados, e execuções podem ser canceladas.
7. Consulte valores, distribuições, média esperada numérica, uso de tokens e resposta original. Exporte JSON, JSONL ou CSV e reutilize configurações do histórico.

## Significado dos scores

- Em `tree`, probabilidades são normalizadas entre os valores permitidos de cada campo. Elas não são confiança calibrada, acurácia ou probabilidade objetiva de um evento real.
- Em `greedy`, `probability` é a pontuação do caminho escolhido; a distribuição completa fica ausente (`null`). `auto` escolhe por campo usando `tree_max`.
- `aggregate: mean` preserva o comportamento original: `decision` contém o valor permitido mais próximo da média. `expected_value` contém a média não arredondada quando a distribuição completa está disponível. Mediana/moda também são suportadas.
- Os campos compartilham a entrada, mas não condicionam suas respostas nas decisões dos outros campos. Perguntas dependentes exigem outra etapa explícita.
- A marca **Revisar** é uma regra local baseada no limiar configurado ou em erro de execução; não altera a saída do modelo.
- O tempo por decisão mostrado em lote é a média do tempo da requisição dividida pelo número de resultados. `raw.timings` e `batch_roundtrip_ms` preservam as medidas do lote.

## Limites e persistência

Imagens de entrada: JPEG, PNG, WebP, BMP e TIFF de página única. Vídeo: MP4, MOV, MKV, AVI, WebM e M4V, sujeito aos codecs disponíveis no OpenCV. Áudio não é processado. Vídeos são amostrados como imagens com timestamps; não há tracking, memória temporal entre janelas, streaming RTSP ou decodificador de vídeo dentro do modelo.

O aplicativo aplica orientação EXIF, reduz o lado máximo sem ampliar e converte para JPEG conforme a qualidade configurada. Até 512 MiB por arquivo, 2 GiB por upload e 500 arquivos por envio/seleção. Até 5.000 quadros por vídeo e 20.000 decisões por execução. Lotes são divididos por quantidade de imagens e tamanho estimado da requisição.

O endpoint nativo aceita 1–256 contextos, até 16 imagens por contexto, 64 imagens por requisição, 8 MiB por data URL e 32 MiB por corpo JSON. O limite efetivo também depende da janela de contexto e da memória KV. Nenhuma URL remota ou caminho local de imagem é baixado/lido pelo endpoint de decisão; somente data URLs JPEG/PNG. Contextos visuais são prefetched individualmente e as alternativas compartilham seu KV. Não existe cache visual persistente entre requisições nesta versão; texto mantém o cache anterior.

`data/` contém banco SQLite, uploads, miniaturas e quadros usados nos resultados. `STUDIO_DATA_DIR` altera esse diretório. Chaves de provedores ficam na configuração local do banco e não são devolvidas ao navegador ou incluídas em exportações. O banco não é criptografado: proteja a pasta com as permissões do sistema operacional. Remover da seleção não apaga os arquivos da biblioteca. Nenhum mecanismo de limpeza automática remove o histórico.

Após interrupção do processo, execuções inacabadas são marcadas como interrompidas; resultados gravados permanecem. Não há retomada automática. Execute **um worker** de uvicorn por diretório de dados.

## Desenvolvimento e testes

```bash
uv sync --frozen
npm ci
npm run build
uv run pytest -q
```

Sem `LLAMA_TEST_URL`, os testes de integração nativa são pulados. Para executá-los, sirva o pequeno fixture oficial [tinygemma3-GGUF](https://huggingface.co/ggml-org/tinygemma3-GGUF) com `-c 8192 --parallel 1 --decision-seqs 32` e defina:

```powershell
$env:LLAMA_TEST_URL = 'http://127.0.0.1:18080'
$env:LLAMA_TEST_MODEL_DIR = 'C:\caminho\para\fixture'
uv run pytest -q
```

A pasta do fixture precisa conter `11_truck.png` e `91_cat.png`, disponíveis no subdiretório `test/` do modelo. Esse fixture testa mecanismos e produz classificações sem qualidade suficiente para uso real.

Para desenvolvimento da interface, execute `uv run uvicorn backend.app:app --port 8765` e `npm run dev`. O Vite encaminha `/api` para o backend. O acesso normal LAN usa a interface compilada servida pelo próprio FastAPI, sem precisar manter o Vite ativo.

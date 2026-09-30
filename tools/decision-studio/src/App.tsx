import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Braces,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Download,
  FileImage,
  Film,
  FolderOpen,
  History,
  ImagePlus,
  Layers3,
  Loader2,
  Network,
  Play,
  Plus,
  Radio,
  RotateCcw,
  Save,
  Scan,
  Server,
  Settings2,
  ShieldCheck,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { active, api, displayValue, statusText, timecode, upload } from "./api";
import type {
  Config,
  Job,
  Media,
  Probe,
  Provider,
  Result,
  TollProfile,
} from "./types";

import { TollTable, TollResult } from "./Toll";
import TollConfig from "./TollConfig";

type Page = "workspace" | "history" | "providers";
const bytes = (n: number) =>
  n > 1024 * 1024
    ? `${(n / 1024 / 1024).toFixed(1)} MB`
    : `${Math.round(n / 1024)} KB`;
function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </Field>
  );
}
function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function ResultCard({ result: r, job }: { result: Result; job: Job }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <article
      className={`result-card ${r.status === "error" ? "result-error" : ""}`}
    >
      <div className="result-head">
        <div className="result-thumbs">
          {r.samples.slice(0, 3).map((s, i) => (
            <img
              key={i}
              src={`/api/jobs/${job.id}/frames/${r.seq}/${i}`}
              alt={s.name}
            />
          ))}
        </div>
        <div className="result-source">
          <strong>
            {r.samples.length > 1
              ? `${r.samples.length} imagens · conjunto ${r.seq + 1}`
              : r.samples[0]?.name}
          </strong>
          <span>
            {r.samples[0]?.timestamp != null
              ? `${timecode(r.samples[0].timestamp)}${r.samples.length > 1 ? " → " + timecode(r.samples.at(-1)!.timestamp || 0) : ""}`
              : r.samples[0]?.relative_path}{" "}
            · #{r.seq + 1}
          </span>
        </div>
        <Badge
          tone={
            r.status === "error" ? "danger" : r.needs_review ? "amber" : "green"
          }
        >
          {r.status === "error"
            ? "Erro"
            : r.needs_review
              ? "Revisar"
              : "Concluído"}
        </Badge>
      </div>
      {r.error ? (
        <p className="error-text">{r.error}</p>
      ) : r.classification ? (
        <TollResult result={r.classification} />
      ) : (
        <div className="decision-fields">
          {Object.entries(r.fields || {}).map(([name, f]) => (
            <div className="decision-field" key={name}>
              <div>
                <span>{name}</span>
                <strong>{displayValue(f.value)}</strong>
              </div>
              <div className="score-line">
                {f.probability == null ? (
                  <small>JSON gerado · sem probabilidade</small>
                ) : (
                  <>
                    <div className="score-track">
                      <span style={{ width: `${f.probability * 100}%` }} />
                    </div>
                    <b>{(f.probability * 100).toFixed(1)}%</b>
                  </>
                )}
              </div>
              {f.expected_value != null && (
                <small>Média esperada: {f.expected_value.toFixed(3)}</small>
              )}
              {f.tree === false && <small>Pontuação do caminho greedy</small>}
              {expanded && f.distribution && (
                <div className="distribution">
                  {f.distribution.map((p, i) => (
                    <div key={i}>
                      <span>{displayValue(p.value)}</span>
                      <progress value={p.probability} max={1} />
                      <span>{(p.probability * 100).toFixed(2)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="result-foot">
        <small>
          <Clock3 size={12} />{" "}
          {r.amortized_ms != null
            ? `${Math.round(r.amortized_ms)} ms / decisão`
            : "—"}{" "}
          {r.usage?.image_tokens != null &&
            ` · ${r.usage.image_tokens} tokens visuais`}
        </small>
        <button className="text-button" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Recolher" : "Mídias e dados originais"}{" "}
          <ChevronRight size={13} className={expanded ? "rotate" : ""} />
        </button>
      </div>
      {expanded && (
        <div className="raw-output">
          <div className="sample-list">
            {r.samples.map((s, i) => (
              <span key={i}>
                {i + 1}. {s.relative_path || s.name}
                {s.timestamp != null && ` · ${timecode(s.timestamp)}`}
              </span>
            ))}
          </div>
          <details>
            <summary>Resposta original</summary>
            <pre>{JSON.stringify(r.raw || { error: r.error }, null, 2)}</pre>
          </details>
          <details>
            <summary>Configuração e identificação das entradas</summary>
            <pre>{JSON.stringify(r.request, null, 2)}</pre>
          </details>
        </div>
      )}
    </article>
  );
}

function ProvidersPage({
  providers,
  onSave,
  notify,
}: {
  providers: Provider[];
  onSave: (p: Provider[]) => Promise<void>;
  notify: (s: string) => void;
}) {
  const [draft, setDraft] = useState(providers),
    [results, setResults] = useState<Record<string, Probe>>({}),
    [busy, setBusy] = useState("");
  useEffect(() => setDraft(providers), [providers]);
  const patch = (id: string, value: Partial<Provider>) =>
    setDraft((list) => list.map((p) => (p.id === id ? { ...p, ...value } : p)));
  return (
    <div className="wide-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CONEXÕES</p>
          <h1>Seus servidores</h1>
          <p>Conecte modelos locais ou servidores llama.cpp na sua rede.</p>
        </div>
        <button
          className="primary"
          disabled={!!busy}
          onClick={async () => {
            setBusy("save");
            try {
              await onSave(draft);
              notify("Configuração salva.");
            } catch (e) {
              notify(String(e));
            } finally {
              setBusy("");
            }
          }}
        >
          <Save size={16} /> Salvar provedores
        </button>
      </div>
      <div className="provider-grid">
        {draft.map((p, i) => (
          <section className="panel provider-card" key={p.id}>
            <div className="section-title">
              <div>
                <div className="provider-icon">
                  <Server size={20} />
                </div>
                <h2>Servidor {String(i + 1).padStart(2, "0")}</h2>
                <Badge>llama.cpp</Badge>
              </div>
              <button
                className="icon-button"
                title="Remover provedor"
                onClick={() => setDraft(draft.filter((x) => x.id !== p.id))}
              >
                <Trash2 size={16} />
              </button>
            </div>
            <Field label="Nome">
              <input
                value={p.name}
                onChange={(e) => patch(p.id, { name: e.target.value })}
              />
            </Field>
            <Field
              label="Endereço do servidor"
              hint="A conexão parte da máquina que hospeda este aplicativo."
            >
              <input
                placeholder="http://192.168.1.10:8080"
                value={p.base_url}
                onChange={(e) => patch(p.id, { base_url: e.target.value })}
              />
            </Field>
            <div className="two-cols">
              <Field label="Chave da API (opcional)">
                <input
                  type="password"
                  autoComplete="new-password"
                  value={p.api_key ?? ""}
                  placeholder={
                    p.has_api_key
                      ? "Chave salva · digite para substituir"
                      : "Sem autenticação"
                  }
                  onChange={(e) => patch(p.id, { api_key: e.target.value })}
                />
              </Field>
              <NumberField
                label="Tempo limite (s)"
                value={p.timeout_seconds}
                min={5}
                max={1800}
                onChange={(timeout_seconds) => patch(p.id, { timeout_seconds })}
              />
            </div>
            {p.has_api_key && (
              <button
                className="text-button"
                onClick={() => patch(p.id, { api_key: "", has_api_key: false })}
              >
                Limpar chave salva
              </button>
            )}
            <button
              className="secondary test-button"
              disabled={!!busy}
              onClick={async () => {
                setBusy(p.id);
                try {
                  const { has_api_key: _, ...body } = p;
                  const r = await api<Probe>("/providers/test", body);
                  setResults({ ...results, [p.id]: r });
                } catch (e) {
                  notify(String(e));
                } finally {
                  setBusy("");
                }
              }}
            >
              {busy === p.id ? (
                <Loader2 size={15} className="spin" />
              ) : (
                <Radio size={15} />
              )}{" "}
              Testar conexão e listar modelos
            </button>
            {results[p.id] && (
              <div className="connection-result">
                <span className="connection-line">
                  <i /> Conectado · {results[p.id].latency_ms} ms
                </span>
                {results[p.id].models.map((m) => (
                  <div className="model-row" key={m.id}>
                    <code>{m.id}</code>
                    <Badge tone={m.decision?.vision ? "green" : "amber"}>
                      {m.decision?.vision
                        ? "Decisão visual"
                        : "Visão não confirmada"}
                    </Badge>
                  </div>
                ))}
                <small>{results[p.id].message}</small>
              </div>
            )}
          </section>
        ))}
      </div>
      <button
        className="add-provider"
        onClick={() =>
          setDraft([
            ...draft,
            {
              id: `server_${Date.now()}`,
              name: "Novo servidor",
              base_url: "http://127.0.0.1:8080",
              protocol: "llama_cpp",
              timeout_seconds: 120,
            },
          ])
        }
      >
        <Plus size={18} /> Adicionar servidor
      </button>
      <div className="info-card">
        <ShieldCheck size={22} />
        <div>
          <strong>Inferência na sua infraestrutura</strong>
          <p>
            Os arquivos ficam nesta máquina e as imagens selecionadas são
            enviadas ao provedor configurado. Para classificações visuais
            nativas, inicie a branch com um modelo de visão, seu mmproj e{" "}
            <code>--decision-seqs 64</code>.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("workspace"),
    [config, setConfig] = useState<Config | null>(null),
    [providers, setProviders] = useState<Provider[]>([]);
  const [profiles, setProfiles] = useState<TollProfile[]>([]);
  const [media, setMedia] = useState<Media[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [job, setJob] = useState<Job>(),
    [results, setResults] = useState<Result[]>([]);
  const [toast, setToast] = useState(""),
    [busy, setBusy] = useState(""),
    [progress, setProgress] = useState(0),
    [dragging, setDragging] = useState(false),
    [tab, setTab] = useState<"input" | "results">("input"),
    [name, setName] = useState(""),
    [onlyReview, setOnlyReview] = useState(false);
  const filesRef = useRef<HTMLInputElement>(null),
    folderRef = useRef<HTMLInputElement>(null),
    toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const notify = useCallback((msg: string) => {
    setToast(msg.replace(/^Error: /, ""));
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 9000);
  }, []);
  useEffect(() => {
    Promise.all([
      api<{ config: Config }>("/toll/defaults"),
      api<{ providers: Provider[] }>("/settings"),
      api<Media[]>("/media"),
      api<Job[]>("/jobs"),
      api<TollProfile[]>("/toll/profiles"),
    ])
      .then(([d, s, m, j, tables]) => {
        let c = d.config;
        try {
          const saved = JSON.parse(
            localStorage.getItem("cat-studio-config-v1") || "null",
          );
          if (saved) c = { ...c, ...saved };
        } catch {}
        if (!tables.some((p) => p.id === c.toll_profile))
          c.toll_profile = d.config.toll_profile;
        setProfiles(tables);
        setConfig(c);
        setProviders(s.providers);
        setMedia(m);
        setJobs(j.filter((job) => job.config.task === "toll_cat"));
      })
      .catch((e) => notify(String(e)));
    return () => clearTimeout(toastTimer.current);
  }, [notify]);
  useEffect(() => {
    if (config)
      localStorage.setItem("cat-studio-config-v1", JSON.stringify(config));
  }, [config]);
  const refreshJob = useCallback(async (id: string, limit = 100) => {
    const [j, r] = await Promise.all([
      api<Job>(`/jobs/${id}`),
      api<{ items: Result[] }>(`/jobs/${id}/results?limit=${limit}`),
    ]);
    setJob(j);
    setResults(r.items);
    setJobs((old) => [j, ...old.filter((x) => x.id !== j.id)]);
  }, []);
  useEffect(() => {
    if (!job || !active(job)) return;
    const id = job.id;
    let disposed = false;
    const timer = setInterval(async () => {
      try {
        const [j, r] = await Promise.all([
          api<Job>(`/jobs/${id}`),
          api<{ items: Result[] }>(
            `/jobs/${id}/results?offset=${results.length}&limit=100`,
          ),
        ]);
        if (disposed) return;
        setJob(j);
        setJobs((old) => [j, ...old.filter((x) => x.id !== id)]);
        setResults((old) => [
          ...old,
          ...r.items.filter((row) => !old.some((o) => o.seq === row.seq)),
        ]);
      } catch (e) {
        if (!disposed) notify(String(e));
      }
    }, 1500);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [job?.id, job?.status, results.length, notify]);
  async function loadJob(j: Job) {
    setPage("workspace");
    setTab("results");
    setOnlyReview(false);
    try {
      await refreshJob(j.id);
    } catch (e) {
      notify(String(e));
    }
  }
  async function addFiles(list: File[]) {
    if (!list.length || busy) return;
    setBusy("upload");
    setProgress(0);
    try {
      const r = await upload(list, setProgress);
      setMedia((old) => [...r.media, ...old]);
      setSelected((old) => [...old, ...r.media.map((m) => m.id)]);
      setTab("input");
      notify(
        `${r.media.length} arquivo(s) importado(s).${r.errors.length ? " " + r.errors.map((e) => `${e.name}: ${e.error}`).join(" · ") : ""}`,
      );
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy("");
    }
  }
  async function run() {
    if (!config) return;
    setBusy("run");
    try {
      const j = await api<Job>("/toll/jobs", {
        name: name.trim() || `CAT ${new Date().toLocaleString("pt-BR")}`,
        media_ids: selected,
        config,
      });
      setResults([]);
      setJob(j);
      setJobs((old) => [j, ...old]);
      setTab("results");
      setOnlyReview(false);
    } catch (e) {
      notify(String(e));
    } finally {
      setBusy("");
    }
  }
  const patch = (p: Partial<Config>) =>
    setConfig((c) => (c ? { ...c, ...p } : c));
  const selection = selected
      .map((id) => media.find((m) => m.id === id)!)
      .filter(Boolean),
    videos = selection.filter((m) => m.kind === "video");
  const currentProvider = providers.find((p) => p.id === config?.provider_id);
  const move = (index: number, delta: number) =>
    setSelected((old) => {
      const copy = [...old];
      [copy[index], copy[index + delta]] = [copy[index + delta], copy[index]];
      return copy;
    });
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("workspace");
          }}
        >
          <span className="brand-mark">
            <Scan size={23} />
          </span>
          <span>
            CAT<span className="brand-sub">STUDIO</span>
          </span>
        </a>
        <p className="nav-label">WORKSPACE</p>
        <nav>
          <button
            className={page === "workspace" ? "active" : ""}
            onClick={() => setPage("workspace")}
          >
            <Layers3 size={19} />
            <span>Classificar veículos</span>
          </button>
          <button
            className={page === "history" ? "active" : ""}
            onClick={() => {
              setPage("history");
              api<Job[]>("/jobs")
                .then((j) =>
                  setJobs(j.filter((job) => job.config.task === "toll_cat")),
                )
                .catch((e) => notify(String(e)));
            }}
          >
            <History size={19} />
            <span>Histórico</span>
            {jobs.length > 0 && <em>{jobs.length}</em>}
          </button>
          <button
            className={page === "providers" ? "active" : ""}
            onClick={() => setPage("providers")}
          >
            <Server size={19} />
            <span>Provedores</span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-label">
            <span className="status-dot" />
            <span>LOCAL & LAN</span>
            <Network size={14} />
          </div>
          <p>
            Veículos por categoria.
            <br />
            Na sua infraestrutura.
          </p>
          <span className="version">v0.2 · CAT + llama.cpp</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>
              {page === "workspace"
                ? "Classificação CAT"
                : page === "history"
                  ? "Histórico"
                  : "Provedores"}
            </strong>
          </div>
          <span className="instance">
            <CircleDot size={13} /> {location.host}
          </span>
        </header>
        {page === "providers" ? (
          <ProvidersPage
            providers={providers}
            notify={notify}
            onSave={async (list) => {
              const r = await api<{ providers: Provider[] }>(
                "/settings",
                { providers: list.map(({ has_api_key: _, ...p }) => p) },
                "PUT",
              );
              setProviders(r.providers);
            }}
          />
        ) : page === "history" ? (
          <div className="wide-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">REGISTRO DE EXECUÇÕES</p>
                <h1>Histórico</h1>
                <p>
                  Entradas, configurações e resultados preservados nesta
                  máquina.
                </p>
              </div>
              <Badge>{jobs.length} execuções</Badge>
            </div>
            {!jobs.length ? (
              <div className="empty-state panel">
                <History size={34} />
                <h2>A primeira execução começa aqui</h2>
                <p>
                  Seus resultados aparecerão neste espaço após iniciar uma
                  inferência.
                </p>
                <button
                  className="secondary"
                  onClick={() => setPage("workspace")}
                >
                  Abrir workspace
                </button>
              </div>
            ) : (
              <div className="panel history-list">
                {jobs.map((j) => (
                  <button
                    className="history-row"
                    key={j.id}
                    onClick={() => loadJob(j)}
                  >
                    <div className="history-icon">
                      <Layers3 size={18} />
                    </div>
                    <div>
                      <strong>{j.name}</strong>
                      <small>
                        {new Date(j.created_at).toLocaleString("pt-BR")} ·{" "}
                        {j.provider.name}
                      </small>
                    </div>
                    <span>
                      {j.completed}/{j.total} classificações
                    </span>
                    <Badge
                      tone={
                        j.status === "completed"
                          ? "green"
                          : j.status === "failed"
                            ? "danger"
                            : ""
                      }
                    >
                      {statusText[j.status]}
                    </Badge>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : !config ? (
          <div className="empty-state">
            <Loader2 className="spin" />
            <p>Preparando workspace…</p>
          </div>
        ) : (
          <>
            <div className="workspace-heading">
              <div>
                <p className="eyebrow">
                  <span /> CATEGORIAS DE PEDÁGIO
                </p>
                <h1>Um veículo. Todas as hipóteses.</h1>
                <p>
                  Envie imagens ou vídeos. Compare os CAT e veja a escolha do
                  modelo.
                </p>
              </div>
              <div className="heading-actions">
                {active(job) && (
                  <button
                    className="secondary"
                    onClick={() =>
                      api(`/jobs/${job!.id}/cancel`, {})
                        .then(() => notify("Cancelamento solicitado."))
                        .catch((e) => notify(String(e)))
                    }
                  >
                    <Square size={14} /> Cancelar
                  </button>
                )}
                <button
                  className="primary run-button"
                  disabled={!selected.length || !currentProvider || !!busy}
                  onClick={run}
                >
                  {busy === "run" ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Play size={16} fill="currentColor" />
                  )}{" "}
                  Classificar veículos <span>{selected.length}</span>
                </button>
              </div>
            </div>
            <div className="workspace-grid">
              <main className="workspace-content">
                <div className="workspace-tabs">
                  <button
                    className={tab === "input" ? "selected" : ""}
                    onClick={() => setTab("input")}
                  >
                    <FileImage size={16} /> Entradas{" "}
                    <span>{selected.length}</span>
                  </button>
                  <button
                    className={tab === "results" ? "selected" : ""}
                    onClick={() => setTab("results")}
                  >
                    <Braces size={16} /> Resultados{" "}
                    {job && <span>{job.completed}</span>}
                  </button>
                </div>
                {tab === "input" ? (
                  <>
                    <section
                      className={`dropzone ${dragging ? "dragging" : ""}`}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragging(true);
                      }}
                      onDragLeave={() => setDragging(false)}
                      onDrop={(e) => {
                        e.preventDefault();
                        setDragging(false);
                        addFiles(Array.from(e.dataTransfer.files));
                      }}
                    >
                      <div className="upload-glyph">
                        <ImagePlus size={26} />
                        <span>
                          <Plus size={12} />
                        </span>
                      </div>
                      <h2>
                        {busy === "upload"
                          ? `Importando arquivos · ${progress}%`
                          : "Adicione as mídias dos veículos"}
                      </h2>
                      <p>
                        Arraste imagens e vídeos para cá ou escolha os arquivos.
                      </p>
                      <div className="upload-actions">
                        <button
                          className="secondary"
                          disabled={!!busy}
                          onClick={() => filesRef.current?.click()}
                        >
                          <Upload size={15} /> Selecionar arquivos
                        </button>
                        <button
                          className="text-button"
                          disabled={!!busy}
                          onClick={() => folderRef.current?.click()}
                        >
                          <FolderOpen size={16} /> Importar diretório
                        </button>
                      </div>
                      <small>
                        JPG, PNG, WEBP, TIFF · MP4, MOV, MKV e mais · até 512 MB
                        por arquivo
                      </small>
                      {busy === "upload" && (
                        <progress
                          className="upload-progress"
                          value={progress}
                          max={100}
                        />
                      )}
                      <input
                        type="file"
                        hidden
                        multiple
                        ref={filesRef}
                        accept=".jpg,.jpeg,.png,.webp,.bmp,.tif,.tiff,.mp4,.mkv,.mov,.avi,.webm,.m4v"
                        onChange={(e) => {
                          addFiles(Array.from(e.target.files || []));
                          e.target.value = "";
                        }}
                      />
                      <input
                        type="file"
                        hidden
                        multiple
                        ref={folderRef}
                        {...{ webkitdirectory: "", directory: "" }}
                        onChange={(e) => {
                          addFiles(Array.from(e.target.files || []));
                          e.target.value = "";
                        }}
                      />
                    </section>
                    <section className="panel media-panel">
                      <div className="section-title">
                        <div>
                          <h2>Seleção de entrada</h2>
                          <Badge>{selection.length}</Badge>
                        </div>
                        {selected.length > 0 && (
                          <button
                            className="text-button"
                            onClick={() => setSelected([])}
                          >
                            Limpar seleção
                          </button>
                        )}
                      </div>
                      {!selection.length ? (
                        <div className="small-empty">
                          <FileImage size={23} />
                          <p>
                            Nenhum arquivo selecionado.
                            <br />
                            <span>
                              Importe imagens, uma pasta ou um vídeo para
                              começar.
                            </span>
                          </p>
                        </div>
                      ) : (
                        <div className="media-list">
                          {selection.map((m, i) => (
                            <div className="media-row" key={m.id}>
                              <span className="media-index">{i + 1}</span>
                              <img src={`/api/media/${m.id}/preview`} alt="" />
                              <div className="media-name">
                                <strong title={m.relative_path}>
                                  {m.name}
                                </strong>
                                <small>
                                  {m.kind === "video" ? (
                                    <Film size={11} />
                                  ) : (
                                    <FileImage size={11} />
                                  )}{" "}
                                  {m.width}×{m.height} ·{" "}
                                  {m.duration
                                    ? timecode(m.duration) + " · "
                                    : ""}
                                  {bytes(m.size)}
                                </small>
                                <span>
                                  {m.relative_path !== m.name
                                    ? m.relative_path
                                    : ""}
                                </span>
                              </div>
                              <div className="media-actions">
                                <button
                                  className="icon-button"
                                  title="Mover para cima"
                                  disabled={i === 0}
                                  onClick={() => move(i, -1)}
                                >
                                  <ArrowUp size={13} />
                                </button>
                                <button
                                  className="icon-button"
                                  title="Mover para baixo"
                                  disabled={i === selected.length - 1}
                                  onClick={() => move(i, 1)}
                                >
                                  <ArrowDown size={13} />
                                </button>
                                <button
                                  className="icon-button"
                                  title={`Retirar ${m.name}`}
                                  onClick={() =>
                                    setSelected(
                                      selected.filter((id) => id !== m.id),
                                    )
                                  }
                                >
                                  <X size={15} />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      {media.some((m) => !selected.includes(m.id)) && (
                        <details className="library">
                          <summary>
                            <FolderOpen size={14} /> Biblioteca local (
                            {
                              media.filter((m) => !selected.includes(m.id))
                                .length
                            }
                            )
                          </summary>
                          <div className="library-grid">
                            {media
                              .filter((m) => !selected.includes(m.id))
                              .map((m) => (
                                <button
                                  key={m.id}
                                  onClick={() =>
                                    setSelected([...selected, m.id])
                                  }
                                >
                                  <img
                                    src={`/api/media/${m.id}/preview`}
                                    alt=""
                                    loading="lazy"
                                  />
                                  <span>{m.name}</span>
                                  <Plus size={14} />
                                </button>
                              ))}
                          </div>
                        </details>
                      )}
                    </section>
                    <TollTable
                      profile={profiles.find(
                        (p) => p.id === config.toll_profile,
                      )}
                    />
                  </>
                ) : !job ? (
                  <div className="panel empty-state">
                    <Braces size={34} />
                    <h2>O CAT sugerido e todas as alternativas</h2>
                    <p>
                      Classifique os veículos para comparar os scores por CAT e
                      identificar os casos para revisão.
                    </p>
                  </div>
                ) : (
                  <>
                    <section className="panel execution-panel">
                      <div className="section-title">
                        <div>
                          {active(job) ? (
                            <Loader2 size={17} className="spin" />
                          ) : (
                            <Check size={17} />
                          )}
                          <h2>{job.name}</h2>
                        </div>
                        <Badge tone={job.status === "completed" ? "green" : ""}>
                          {statusText[job.status]}
                        </Badge>
                      </div>
                      <progress value={job.completed} max={job.total || 1} />
                      <div className="execution-stats">
                        <div>
                          <strong>
                            {job.completed}
                            <small> / {job.total}</small>
                          </strong>
                          <span>classificações processadas</span>
                        </div>
                        <div>
                          <strong>{job.review}</strong>
                          <span>para revisão</span>
                        </div>
                        <div>
                          <strong>{job.failed}</strong>
                          <span>erros</span>
                        </div>
                        <div>
                          <strong>
                            {job.elapsed_ms
                              ? (job.elapsed_ms / 1000).toFixed(1) + "s"
                              : "—"}
                          </strong>
                          <span>tempo total</span>
                        </div>
                      </div>
                      {job.error && <p className="error-text">{job.error}</p>}
                      {job.warnings.map((w, i) => (
                        <p className="warning" key={i}>
                          {w}
                        </p>
                      ))}
                      <div className="execution-actions">
                        <button
                          className="text-button"
                          onClick={() => {
                            setConfig(job.config);
                            setSelected(
                              job.media_ids.filter((id) =>
                                media.some((m) => m.id === id),
                              ),
                            );
                            setName(job.name + " · cópia");
                            setTab("input");
                          }}
                        >
                          <RotateCcw size={14} /> Reutilizar configuração
                        </button>
                        <div>
                          {["json", "jsonl", "csv"].map((format) => (
                            <a
                              className="export-button"
                              key={format}
                              href={`/api/jobs/${job.id}/export?format=${format}`}
                            >
                              <Download size={12} />
                              {format.toUpperCase()}
                            </a>
                          ))}
                        </div>
                      </div>
                    </section>
                    <div className="results-toolbar">
                      <span>
                        {results.length} de {job.completed} resultados
                        carregados
                      </span>
                      <label>
                        <input
                          type="checkbox"
                          checked={onlyReview}
                          onChange={(e) => setOnlyReview(e.target.checked)}
                        />{" "}
                        Só revisão
                      </label>
                    </div>
                    {job.config.pipeline === "native_decision" && (
                      <p className="score-note">
                        Probabilidades relativas às opções permitidas. Não
                        representam acurácia calibrada.
                      </p>
                    )}
                    {results
                      .filter((r) => !onlyReview || r.needs_review)
                      .map((r) => (
                        <ResultCard key={r.seq} result={r} job={job} />
                      ))}
                    {active(job) && (
                      <div className="working-indicator">
                        <Loader2 size={16} className="spin" /> Processando no
                        servidor · resultados salvos progressivamente
                      </div>
                    )}
                    {results.length < job.completed && (
                      <button
                        className="secondary"
                        onClick={async () => {
                          try {
                            const r = await api<{ items: Result[] }>(
                              `/jobs/${job.id}/results?offset=${results.length}&limit=100`,
                            );
                            setResults([...results, ...r.items]);
                          } catch (e) {
                            notify(String(e));
                          }
                        }}
                      >
                        Carregar mais resultados
                      </button>
                    )}
                  </>
                )}
              </main>
              <TollConfig
                config={config}
                patch={patch}
                profiles={profiles}
                providers={providers}
                videos={videos.length > 0}
                name={name}
                setName={setName}
                manage={() => setPage("providers")}
                notify={notify}
              />
            </div>
          </>
        )}
      </div>
      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button
            className="icon-button"
            onClick={() => setToast("")}
            aria-label="Fechar aviso"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

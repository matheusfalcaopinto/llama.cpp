import { useState, type ReactNode } from "react";
import {
  ArrowUpRight,
  Film,
  Loader2,
  Radio,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { api } from "./api";
import type { Config, Probe, Provider, TollProfile } from "./types";

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
  min,
  max,
  step = 1,
  change,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  change: (n: number) => void;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => change(Number(e.target.value))}
      />
    </Field>
  );
}

export default function TollConfig({
  config: c,
  patch,
  profiles,
  providers,
  videos,
  name,
  setName,
  manage,
  notify,
}: {
  config: Config;
  patch: (p: Partial<Config>) => void;
  profiles: TollProfile[];
  providers: Provider[];
  videos: boolean;
  name: string;
  setName: (name: string) => void;
  manage: () => void;
  notify: (msg: string) => void;
}) {
  const [testing, setTesting] = useState(false);
  const [probe, setProbe] = useState<{ provider: string; result: Probe }>();
  const provider = providers.find((p) => p.id === c.provider_id);
  const modelProbe =
    probe?.provider === JSON.stringify(provider) ? probe.result : undefined;
  return (
    <aside className="config-panel">
      <div className="config-title">
        <Settings2 size={17} />
        <h2>Classificação CAT</h2>
        <span className="tiny-dot" />
      </div>
      <div className="config-section">
        <p className="config-label">01 / TABELA DE PEDÁGIO</p>
        <Field
          label="Perfil de categorias"
          hint="O CAT depende da tabela escolhida, não apenas do número de eixos."
        >
          <select
            value={c.toll_profile}
            onChange={(e) => patch({ toll_profile: e.target.value })}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <p className="config-help">
          O modelo avalia os CAT desta tabela e pode escolher indeterminado.
          Categorias administrativas exigem comprovação.
        </p>
      </div>
      <div className="config-section">
        <p className="config-label">02 / SERVIDOR & MODELO</p>
        <Field label="Provedor">
          <select
            value={c.provider_id}
            onChange={(e) => patch({ provider_id: e.target.value, model: "" })}
          >
            <option value="" disabled>
              Selecione um servidor
            </option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Modelo"
          hint="Deixe vazio para usar o modelo carregado no servidor."
        >
          <input
            list="model-options"
            value={c.model}
            placeholder="Modelo de visão do servidor"
            onChange={(e) => patch({ model: e.target.value })}
          />
          <datalist id="model-options">
            {modelProbe?.models.map((m) => (
              <option key={m.id} value={m.id} />
            ))}
          </datalist>
        </Field>
        <div className="provider-link">
          <button
            className="text-button"
            disabled={!provider || testing}
            onClick={async () => {
              if (!provider) return;
              setTesting(true);
              try {
                const { has_api_key: _, ...body } = provider;
                setProbe({
                  provider: JSON.stringify(provider),
                  result: await api<Probe>("/providers/test", body),
                });
              } catch (e) {
                notify(String(e));
              } finally {
                setTesting(false);
              }
            }}
          >
            {testing ? (
              <Loader2 size={13} className="spin" />
            ) : (
              <Radio size={13} />
            )}{" "}
            Verificar servidor
          </button>
          <button className="text-button" onClick={manage}>
            Gerenciar <ArrowUpRight size={12} />
          </button>
        </div>
        {modelProbe && (
          <p
            className={`connection-summary ${modelProbe.models.some((m) => m.decision?.vision) ? "ok" : "warning"}`}
          >
            {modelProbe.models.some((m) => m.decision?.vision)
              ? "Decisão visual disponível"
              : "Decisão visual não confirmada pelo servidor"}
          </p>
        )}
        <p className="config-help">
          Inferência nativa com distribuição completa por CAT. Requer modelo de
          visão e mmproj no nosso fork do llama.cpp.
        </p>
      </div>
      <div className="config-section">
        <p className="config-label">03 / VEÍCULOS & MÍDIAS</p>
        <Field label="Como analisar a seleção">
          <select
            value={c.grouping}
            onChange={(e) =>
              patch({ grouping: e.target.value as Config["grouping"] })
            }
          >
            <option value="individual">Um veículo por arquivo</option>
            <option value="together">Mesmo veículo em todas as mídias</option>
            <option value="directory">Um veículo por pasta</option>
          </select>
        </Field>
        <p className="config-help">
          {c.grouping === "individual"
            ? "Cada imagem ou vídeo recebe um resultado. Os quadros de um vídeo são avaliados juntos."
            : "Reúna apenas vistas do mesmo veículo. Cada conjunto aceita até 16 imagens/quadros no total."}{" "}
          Separe arquivos ou recorte o trecho se houver veículos diferentes.
        </p>
        {videos && (
          <details open className="video-settings">
            <summary>
              <Film size={14} /> Quadros do vídeo
            </summary>
            <Field label="Amostragem">
              <select
                value={c.video_mode}
                onChange={(e) =>
                  patch({ video_mode: e.target.value as Config["video_mode"] })
                }
              >
                <option value="uniform">Distribuir no trecho inteiro</option>
                <option value="interval">Por intervalo, desde o início</option>
              </select>
            </Field>
            <NumberField
              label="Quadros por vídeo"
              value={c.max_frames}
              min={1}
              max={16}
              change={(max_frames) => patch({ max_frames })}
            />
            {c.video_mode === "interval" && (
              <NumberField
                label="Intervalo (s)"
                value={c.frame_interval}
                min={0.04}
                max={3600}
                step={0.1}
                change={(frame_interval) => patch({ frame_interval })}
              />
            )}
            <div className="two-cols">
              <NumberField
                label="Início (s)"
                value={c.start_seconds}
                min={0}
                max={86400}
                step={0.1}
                change={(start_seconds) => patch({ start_seconds })}
              />
              <Field label="Fim (s)">
                <input
                  type="number"
                  min={0}
                  max={86400}
                  step={0.1}
                  placeholder="Final do vídeo"
                  value={c.end_seconds ?? ""}
                  onChange={(e) =>
                    patch({
                      end_seconds: e.target.value
                        ? Number(e.target.value)
                        : null,
                    })
                  }
                />
              </Field>
            </div>
            <small>
              O mesmo veículo deve aparecer no trecho escolhido. Os timestamps
              ficam registrados no resultado.
            </small>
          </details>
        )}
        <Field label="Nome da execução">
          <input
            value={name}
            placeholder="Gerado automaticamente"
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
      </div>
      <div className="config-section">
        <details>
          <summary>
            Parâmetros de análise <Settings2 size={14} />
          </summary>
          <NumberField
            label="Revisar se score menor que"
            value={c.review_threshold}
            min={0}
            max={1}
            step={0.05}
            change={(review_threshold) => patch({ review_threshold })}
          />
          <NumberField
            label="Revisar se diferença menor que"
            value={c.review_margin}
            min={0}
            max={1}
            step={0.05}
            change={(review_margin) => patch({ review_margin })}
          />
          <div className="two-cols">
            <NumberField
              label="Lado máximo (px)"
              value={c.image_max_side}
              min={224}
              max={4096}
              change={(image_max_side) => patch({ image_max_side })}
            />
            <NumberField
              label="Qualidade JPEG"
              value={c.jpeg_quality}
              min={40}
              max={100}
              change={(jpeg_quality) => patch({ jpeg_quality })}
            />
          </div>
          <NumberField
            label="Veículos por lote de inferência"
            value={c.batch_size}
            min={1}
            max={64}
            change={(batch_size) => patch({ batch_size })}
          />
          <small>
            Scores comparam hipóteses permitidas. Os limiares sinalizam revisão
            e não alteram a escolha do modelo.
          </small>
        </details>
      </div>
      <div className="config-footer">
        <ShieldCheck size={14} />
        <span>Mídias, tabela e resultados salvos localmente</span>
      </div>
    </aside>
  );
}

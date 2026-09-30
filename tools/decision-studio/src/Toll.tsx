import { ArrowUpRight, Check, ListOrdered, ShieldCheck } from "lucide-react";
import type { Classification, TollProfile } from "./types";

export const catLabel = (code: string) => code.replace("CAT_", "CAT ");
const percent = (p: number) => `${(p * 100).toFixed(1)}%`;

export function TollTable({ profile }: { profile?: TollProfile }) {
  if (!profile) return null;
  return (
    <section className="panel toll-table-panel">
      <div className="section-title">
        <div>
          <ListOrdered size={17} />
          <h2>Tabela de categorias</h2>
        </div>
        <a
          className="text-button"
          href={profile.source_url}
          target="_blank"
          rel="noreferrer"
        >
          Fonte ANTT <ArrowUpRight size={13} />
        </a>
      </div>
      <p className="muted section-intro">
        {profile.name}. Escolha baseada em tipo, eixos e rodagem.
      </p>
      <div className="toll-table-scroll">
        <table className="toll-table">
          <thead>
            <tr>
              <th>CAT</th>
              <th>Veículo</th>
              <th>Eixos</th>
              <th>Rodagem</th>
              <th>Fator</th>
            </tr>
          </thead>
          <tbody>
            {profile.categories.map((c) => (
              <tr key={c.code}>
                <td>
                  <b>{catLabel(c.code)}</b>
                </td>
                <td>
                  {c.label}
                  {!c.visual && (
                    <small className="administrative-note">
                      Depende de comprovação administrativa
                    </small>
                  )}
                </td>
                <td>{c.axles ?? "—"}</td>
                <td>{c.wheels ?? "—"}</td>
                <td>
                  {c.multiplier == null
                    ? "—"
                    : `${c.multiplier.toLocaleString("pt-BR")}x`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="toll-table-note">
        <ShieldCheck size={14} /> Sem evidência suficiente, o modelo pode
        escolher indeterminado. O fator identifica a tabela; esta aplicação não
        calcula cobrança.
      </p>
    </section>
  );
}

export function TollResult({ result: c }: { result: Classification }) {
  const winner = c.ranking.find((r) => r.selected);
  return (
    <div className="toll-result">
      <div className={`cat-summary ${c.needs_review ? "cat-review" : ""}`}>
        <div>
          <small>
            {c.suggested_cat
              ? "CAT sugerido pelo modelo"
              : "Classificação inconclusiva"}
          </small>
          <strong>
            {c.suggested_cat ? catLabel(c.suggested_cat) : "Indeterminado"}
          </strong>
          <p>{winner?.label ?? "Nenhuma categoria atribuída"}</p>
        </div>
        <div className="cat-confidence">
          <b>{percent(c.selected_probability)}</b>
          <small>score da escolha</small>
        </div>
      </div>
      <p className="cat-profile">
        {c.profile_name} · versão {c.profile_version}
      </p>
      {c.reasons.length > 0 && (
        <ul className="review-reasons">
          {c.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <div className="cat-ranking-title">
        <span>Ranking de todos os CAT</span>
        <small>Diferença entre primeiras hipóteses: {percent(c.margin)}</small>
      </div>
      <div className="cat-ranking">
        {c.ranking.map((r) => (
          <div
            className={`cat-ranking-row ${r.selected ? "chosen" : ""}`}
            key={r.code}
          >
            <span className="cat-code">
              {catLabel(r.code)}
              {r.selected && <Check size={13} />}
            </span>
            <div className="cat-details">
              <span>{r.label}</span>
              <small>
                {r.visual
                  ? `${r.axles == null ? "Por tipo de veículo" : `${r.axles} eixos · ${r.wheels}`} `
                  : "Requer comprovação administrativa; sem score visual"}
              </small>
            </div>
            {r.probability == null ? (
              <span className="muted">—</span>
            ) : (
              <div className="cat-score">
                <progress value={r.probability} max={1} />
                <b>{percent(r.probability)}</b>
              </div>
            )}
          </div>
        ))}
      </div>
      <div
        className={`uncertain-score ${c.selected === "INDETERMINADO" ? "chosen" : ""}`}
      >
        <span>Indeterminado · evidência insuficiente ou fora da tabela</span>
        <b>{percent(c.uncertain_probability)}</b>
      </div>
    </div>
  );
}

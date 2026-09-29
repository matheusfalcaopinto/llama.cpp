export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
export function upload(
  files: File[],
  onProgress: (n: number) => void,
): Promise<{
  media: import("./types").Media[];
  errors: { name: string; error: string }[];
}> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(),
      form = new FormData();
    files.forEach((file) => form.append("files", file));
    form.append(
      "paths",
      JSON.stringify(files.map((f) => f.webkitRelativePath || f.name)),
    );
    xhr.open("POST", "/api/media");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => reject(new Error("Falha de conexão durante o envio."));
    xhr.onload = () => {
      try {
        const value = JSON.parse(xhr.responseText);
        xhr.status < 300
          ? resolve(value)
          : reject(new Error(value.detail || "Falha no envio."));
      } catch {
        reject(new Error("Resposta de upload inválida."));
      }
    };
    xhr.send(form);
  });
}
export const active = (job?: import("./types").Job) =>
  !!job && ["queued", "running"].includes(job.status);
export const statusText: Record<string, string> = {
  queued: "Na fila",
  running: "Em execução",
  completed: "Concluída",
  partial: "Parcial",
  failed: "Falhou",
  cancelled: "Cancelada",
  interrupted: "Interrompida",
};
export const displayValue = (value: unknown) =>
  typeof value === "boolean" ? (value ? "Sim" : "Não") : String(value);
export const timecode = (seconds: number) =>
  `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toFixed(2).padStart(5, "0")}`;

import { useCallback, useEffect, useRef, useState } from "react";
import * as client from "../api/client";
import type {
  OllamaModel,
  OllamaRecommended,
  OllamaStatus,
  Settings,
} from "../types";

interface Props {
  settings: Settings;
  /** Ollama base URL (OpenAI-compat base, no /v1). */
  ollamaUrl: string;
  onUrlChange: (url: string) => void;
  /** Wire the chosen local model into the A4 slot. */
  onSelectModel: (name: string, baseUrl: string) => void;
  /** Currently-configured A4 model, to mark the active row. */
  currentA4Model?: string;
}

interface PullState {
  status: string;
  pct: number | null; // null = indeterminate
  error?: string;
}

function fmtSize(bytes?: number): string {
  if (!bytes) return "";
  const gb = bytes / 1e9;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  return `${(bytes / 1e6).toFixed(0)} MB`;
}

export function OllamaManager({
  settings,
  ollamaUrl,
  onUrlChange,
  onSelectModel,
  currentA4Model,
}: Props) {
  const [status, setStatus] = useState<OllamaStatus | null>(null);
  const [installed, setInstalled] = useState<OllamaModel[]>([]);
  const [recommended, setRecommended] = useState<OllamaRecommended[]>([]);
  const [checking, setChecking] = useState(false);
  const [pulls, setPulls] = useState<Record<string, PullState>>({});

  const aborters = useRef<Map<string, AbortController>>(new Map());

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      const st = await client.ollamaStatus(settings, ollamaUrl);
      setStatus(st);
      if (st.running) {
        setInstalled(await client.ollamaModels(settings, ollamaUrl));
      } else {
        setInstalled([]);
      }
    } catch (e) {
      setStatus({ running: false, base_url: ollamaUrl, error: String(e) });
      setInstalled([]);
    } finally {
      setChecking(false);
    }
  }, [settings, ollamaUrl]);

  // Load the curated list once.
  useEffect(() => {
    client.ollamaRecommended(settings).then(setRecommended).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-check whenever the URL settles (debounced).
  useEffect(() => {
    const t = setTimeout(refresh, 400);
    return () => clearTimeout(t);
  }, [refresh]);

  // Cancel any in-flight pulls on unmount.
  useEffect(() => {
    const map = aborters.current;
    return () => map.forEach((a) => a.abort());
  }, []);

  const installedNames = new Set(installed.map((m) => m.name));

  async function pull(name: string) {
    if (aborters.current.has(name)) return; // already pulling
    const ac = new AbortController();
    aborters.current.set(name, ac);
    setPulls((p) => ({ ...p, [name]: { status: "准备中…", pct: null } }));
    try {
      for await (const ev of client.streamOllamaPull(settings, ollamaUrl, name, ac.signal)) {
        if ("error" in ev) {
          setPulls((p) => ({ ...p, [name]: { status: "失败", pct: null, error: ev.error } }));
          return;
        }
        const pct =
          ev.total && ev.completed != null
            ? Math.min(100, Math.round((ev.completed / ev.total) * 100))
            : null;
        setPulls((p) => ({ ...p, [name]: { status: ev.status, pct } }));
        if (ev.status === "success") {
          // Pulled — refresh the installed list and auto-wire it into A4.
          await refresh();
          onSelectModel(name, ollamaUrl);
        }
      }
    } catch (e) {
      // Aborts land here too; only surface real failures.
      if (!ac.signal.aborted) {
        setPulls((p) => ({ ...p, [name]: { status: "失败", pct: null, error: String(e) } }));
        return;
      }
    } finally {
      aborters.current.delete(name);
      // Clear the progress row shortly after a successful pull.
      setPulls((p) => {
        if (p[name]?.status === "success") {
          const { [name]: _done, ...rest } = p;
          return rest;
        }
        return p;
      });
    }
  }

  function cancelPull(name: string) {
    aborters.current.get(name)?.abort();
    aborters.current.delete(name);
    setPulls((p) => {
      const { [name]: _gone, ...rest } = p;
      return rest;
    });
  }

  async function remove(name: string) {
    if (!confirm(`删除本地模型 ${name}？`)) return;
    try {
      await client.ollamaDelete(settings, ollamaUrl, name);
      await refresh();
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  }

  return (
    <div className="ollama">
      <div className="ollama__head">
        <div className="ollama__title">
          <span className="ollama__logo">🦙</span>
          <span>本地模型 · Ollama</span>
        </div>
        <div className={`ollama__status ${status?.running ? "up" : "down"}`}>
          <span className="ollama__dot" />
          {checking
            ? "检测中…"
            : status?.running
            ? `运行中 · v${status.version ?? "?"}`
            : "未运行"}
        </div>
      </div>

      <div className="field">
        <label>Ollama 地址</label>
        <div className="ollama__url">
          <input
            type="text"
            value={ollamaUrl}
            onChange={(e) => onUrlChange(e.target.value)}
            placeholder="http://localhost:11434"
            spellCheck={false}
          />
          <button
            className="btn btn--secondary"
            onClick={refresh}
            disabled={checking}
            title="刷新状态与模型列表"
          >
            {checking ? <span className="spinner spinner--sm" /> : "刷新"}
          </button>
        </div>
      </div>

      {!status?.running && (
        <div className="ollama__hint">
          未检测到 Ollama。请在<strong>运行 Autumn 服务端的机器上</strong>启动它：
          <code>ollama serve</code>
          （未安装见 <a href="https://ollama.com/download" target="_blank" rel="noreferrer">ollama.com</a>）。
          <br />
          注意：本地模型需服务端能直接访问该地址；云端容器看不到你机器的 localhost。
        </div>
      )}

      {/* Installed models */}
      {status?.running && installed.length > 0 && (
        <div className="ollama__section">
          <div className="ollama__section-title">已安装</div>
          <div className="ollama__list">
            {installed.map((m) => {
              const active = m.name === currentA4Model;
              return (
                <div key={m.name} className={`ollama__row${active ? " active" : ""}`}>
                  <div className="ollama__row-main">
                    <span className="ollama__name">{m.name}</span>
                    <span className="ollama__meta">
                      {m.parameter_size ? `${m.parameter_size} · ` : ""}
                      {fmtSize(m.size)}
                    </span>
                  </div>
                  <div className="ollama__row-actions">
                    {active ? (
                      <span className="ollama__badge">A4 当前</span>
                    ) : (
                      <button
                        className="btn btn--primary btn--xs"
                        onClick={() => onSelectModel(m.name, ollamaUrl)}
                      >
                        用于 A4
                      </button>
                    )}
                    <button
                      className="btn btn--ghost btn--xs"
                      onClick={() => remove(m.name)}
                      title="删除"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recommended / pullable models */}
      <div className="ollama__section">
        <div className="ollama__section-title">推荐模型（点击拉取即用）</div>
        <div className="ollama__list">
          {recommended.map((r) => {
            const has = installedNames.has(r.name);
            const pulling = pulls[r.name];
            return (
              <div key={r.name} className="ollama__row">
                <div className="ollama__row-main">
                  <span className="ollama__name">
                    {r.label}
                    {r.recommended && <span className="ollama__star" title="推荐">★</span>}
                  </span>
                  <span className="ollama__meta">{r.size} · {r.note}</span>
                  {pulling && (
                    <div className="ollama__progress">
                      <div className="ollama__bar">
                        <div
                          className={`ollama__bar-fill${pulling.pct == null ? " indeterminate" : ""}`}
                          style={pulling.pct != null ? { width: `${pulling.pct}%` } : undefined}
                        />
                      </div>
                      <span className="ollama__progress-text">
                        {pulling.error
                          ? pulling.error
                          : pulling.pct != null
                          ? `${pulling.status} ${pulling.pct}%`
                          : pulling.status}
                      </span>
                    </div>
                  )}
                </div>
                <div className="ollama__row-actions">
                  {has ? (
                    <span className="ollama__badge ollama__badge--ok">已安装</span>
                  ) : pulling && !pulling.error ? (
                    <button
                      className="btn btn--ghost btn--xs"
                      onClick={() => cancelPull(r.name)}
                    >
                      取消
                    </button>
                  ) : (
                    <button
                      className="btn btn--secondary btn--xs"
                      onClick={() => pull(r.name)}
                      disabled={!status?.running}
                      title={status?.running ? "拉取并配置到 A4" : "请先启动 Ollama"}
                    >
                      {pulling?.error ? "重试" : "拉取"}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

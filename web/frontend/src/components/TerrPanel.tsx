import { useEffect, useState } from "react";
import * as client from "../api/client";
import type { Settings, Terr } from "../types";

interface Props {
  settings: Settings;
}

export function TerrPanel({ settings }: Props) {
  const [terrs, setTerrs] = useState<Terr[]>([]);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [settings.serverUrl, settings.authToken]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setTerrs(await client.getTerrs(settings));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function toggle(terr: Terr) {
    if (toggling.has(terr.name)) return;
    const prev = [...terrs];
    setTerrs((ts) => ts.map((t) => t.name === terr.name ? { ...t, enabled: !t.enabled } : t));
    setToggling((s) => new Set([...s, terr.name]));
    try {
      const updated = await client.setTerrEnabled(settings, terr.name, !terr.enabled);
      setTerrs((ts) => ts.map((t) => t.name === terr.name ? updated : t));
    } catch (e) {
      setTerrs(prev);
      setError(String(e));
    } finally {
      setToggling((s) => { const n = new Set(s); n.delete(terr.name); return n; });
    }
  }

  function toggleExpand(name: string) {
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });
  }

  return (
    <div className="panel">
      <div className="panel__header">
        <h2>能力域 (Terr)</h2>
        <button className="btn btn--secondary" style={{ fontSize: 11, padding: "4px 10px" }} onClick={load}>
          刷新
        </button>
      </div>

      <div className="panel__body">
        {error && (
          <div className="error-banner" style={{ borderRadius: "var(--r-md)", border: "1px solid rgba(248 113 113 / 0.2)" }}>
            {error}
            <button className="error-banner__close" onClick={() => setError("")}>✕</button>
          </div>
        )}

        {loading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "var(--xl)" }}>
            <span className="spinner" />
          </div>
        ) : terrs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__icon">⬡</div>
            <div className="empty-state__title">无已注册能力域</div>
            <div className="empty-state__sub">
              在应用启动时通过 <code>register_terr()</code> 或 <code>register_builtins()</code> 注册。
            </div>
          </div>
        ) : (
          <div className="terr-list">
            {terrs.map((terr) => {
              const isExpanded = expanded.has(terr.name);
              const isToggling = toggling.has(terr.name);
              return (
                <div key={terr.name} className={`terr-card${terr.enabled ? "" : " disabled"}`}>
                  <div className="terr-card__header" onClick={() => toggleExpand(terr.name)}>
                    <span
                      style={{
                        fontSize: 10, transform: isExpanded ? "rotate(90deg)" : "none",
                        transition: "transform 0.15s", display: "inline-block", color: "var(--text-3)",
                      }}
                    >
                      ▶
                    </span>
                    <span className="terr-card__name">{terr.name}</span>
                    <div className="terr-card__meta">
                      <span className="badge badge--info">{terr.tools.length}T</span>
                      <span className="badge badge--accent">{terr.skills.length}S</span>
                      <span className={`badge ${terr.enabled ? "badge--success" : "badge--neutral"}`}>
                        {terr.enabled ? "启用" : "停用"}
                      </span>
                      {isToggling ? (
                        <span className="spinner spinner--sm" style={{ margin: "0 4px" }} />
                      ) : (
                        <button
                          className={`terr-toggle${terr.enabled ? " on" : ""}`}
                          onClick={(e) => { e.stopPropagation(); toggle(terr); }}
                          title={terr.enabled ? "停用能力域" : "启用能力域"}
                        >
                          <div className="terr-toggle__pip" />
                        </button>
                      )}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="terr-card__body">
                      <div style={{ color: "var(--text-3)", fontSize: 11 }}>{terr.description}</div>

                      {terr.tools.length > 0 && (
                        <div>
                          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-3)", marginBottom: 4 }}>
                            Tools
                          </div>
                          <div className="callable-list">
                            {terr.tools.map((t) => (
                              <span key={t.name} className="badge badge--info" title={t.description}>
                                {t.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {terr.skills.length > 0 && (
                        <div>
                          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-3)", marginBottom: 4 }}>
                            Skills
                          </div>
                          <div className="callable-list">
                            {terr.skills.map((s) => (
                              <span key={s.name} className="badge badge--accent" title={s.description}>
                                {s.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {terr.mcps.length > 0 && (
                        <div>
                          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-3)", marginBottom: 4 }}>
                            MCP Servers
                          </div>
                          <div className="callable-list">
                            {terr.mcps.map((m, i) => (
                              <span key={i} className="badge badge--neutral">{m.name}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

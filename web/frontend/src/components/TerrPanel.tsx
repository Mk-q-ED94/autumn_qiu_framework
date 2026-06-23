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
        <button className="btn btn--secondary btn--compact" onClick={load}>
          刷新
        </button>
      </div>

      <div className="panel__body">
        {error && (
          <div className="error-banner error-banner--panel">
            {error}
            <button className="error-banner__close" onClick={() => setError("")} aria-label="关闭错误提示">×</button>
          </div>
        )}

        {loading ? (
          <div className="panel__loading panel__loading--padded">
            <span className="spinner" />
          </div>
        ) : terrs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__icon">⬡</div>
            <div className="empty-state__title">无已注册能力域</div>
            <div className="empty-state__sub">
              设 <code>AUTUMN_BUILTIN_TERRS=safe</code> 注册 6 个安全域，
              <code>=all</code> 追加 web + knowledge。
              文件系统域需同时设 <code>AUTUMN_FS_ROOT</code>；
              或在代码中调用 <code>register_terr()</code>。
            </div>
          </div>
        ) : (
          <div className="terr-list">
            {terrs.map((terr) => {
              const isExpanded = expanded.has(terr.name);
              const isToggling = toggling.has(terr.name);
              return (
                <div key={terr.name} className={`terr-card${terr.enabled ? "" : " disabled"}`}>
                  <div
                    className="terr-card__header"
                    role="button"
                    tabIndex={0}
                    aria-expanded={isExpanded}
                    onClick={() => toggleExpand(terr.name)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleExpand(terr.name);
                      }
                    }}
                  >
                    <span
                      className={`terr-caret${isExpanded ? " expanded" : ""}`}
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
                        <span className="spinner spinner--sm spinner--inline" />
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
                      <div className="terr-card__description">{terr.description}</div>

                      {terr.tools.length > 0 && (
                        <div>
                          <div className="terr-group__title">
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
                          <div className="terr-group__title">
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
                          <div className="terr-group__title">
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

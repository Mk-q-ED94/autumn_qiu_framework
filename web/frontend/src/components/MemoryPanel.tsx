import { useEffect, useState } from "react";
import * as client from "../api/client";
import type { MemoryArea, MemoryEntry, Settings } from "../types";

interface Props {
  settings: Settings;
}

const AREAS: Array<{ id: MemoryArea; label: string; desc: string }> = [
  { id: "mom1", label: "Mom1", desc: "WP1 短期记忆 · 可读 Mom2/3" },
  { id: "mom2", label: "Mom2", desc: "WP2 任务记忆 · 含共享区" },
  { id: "mom3", label: "Mom3", desc: "WP3 Mission 记忆 · 含共享区" },
];

export function MemoryPanel({ settings }: Props) {
  const [area, setArea] = useState<MemoryArea>("mom1");
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [area, settings.serverUrl, settings.authToken]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setEntries(await client.getMemoryHistory(settings, area));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function format(entry: MemoryEntry): string {
    if (typeof entry === "string") return entry;
    try {
      return JSON.stringify(entry, null, 2);
    } catch {
      return String(entry);
    }
  }

  const current = AREAS.find((a) => a.id === area)!;

  return (
    <div className="panel">
      <div className="panel__header">
        <h2>记忆</h2>
        <button className="btn btn--secondary btn--compact" onClick={load}>
          刷新
        </button>
      </div>

      <div className="memory-tabs">
        {AREAS.map((a) => (
          <button
            key={a.id}
            className={`memory-tab${area === a.id ? " active" : ""}`}
            onClick={() => setArea(a.id)}
          >
            {a.label}
          </button>
        ))}
      </div>

      <div className="panel__body">
        <div className="panel__description">{current.desc}</div>

        {error && (
          <div className="error-banner error-banner--panel">
            {error}
          </div>
        )}

        {loading ? (
          <div className="panel__loading">
            <span className="spinner" />
          </div>
        ) : entries.length === 0 ? (
          <div className="empty-state empty-state--compact">
            <div className="empty-state__icon">◈</div>
            <div className="empty-state__title">暂无记忆条目</div>
            <div className="empty-state__sub">
              当 A1/A2/A3 在对话中读写此区域时，条目会出现在这里。
            </div>
          </div>
        ) : (
          <div className="memory-entries">
            {entries.map((entry, i) => (
              <div key={i} className="memory-entry">{format(entry)}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

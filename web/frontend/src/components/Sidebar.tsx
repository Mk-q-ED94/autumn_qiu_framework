import type { Conversation, HealthStatus } from "../types";

type View = "chat" | "workspace" | "memory" | "settings";

interface Props {
  view: View;
  onView: (v: View) => void;
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  health: HealthStatus;
  onAgentClick: () => void;
}

const NAV_ITEMS: Array<{ view: View; icon: string; label: string; sub: string }> = [
  { view: "chat",      icon: "◎", label: "协作",    sub: "对话与任务" },
  { view: "workspace", icon: "⬡", label: "能力域",   sub: "Terr 管理" },
  { view: "memory",    icon: "◈", label: "记忆",    sub: "Mom1/2/3" },
  { view: "settings",  icon: "⚙", label: "设置",    sub: "模型与服务器" },
];

function healthColor(h: HealthStatus): string {
  if (h.status === "ok" && h.configured) return "var(--success)";
  if (h.status === "ok") return "var(--warning)";
  if (h.status === "error") return "var(--danger)";
  return "var(--muted)";
}

export function Sidebar({
  view, onView, conversations, activeId, onSelect, onNew, onDelete, health, onAgentClick,
}: Props) {
  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar__header">
        <div className="sidebar__logo">秋</div>
        <span className="sidebar__title">Autumn</span>
        <div
          style={{
            marginLeft: "auto",
            width: 8, height: 8,
            borderRadius: "50%",
            background: healthColor(health),
            flexShrink: 0,
          }}
          title={health.configured ? "已配置" : "未配置"}
        />
      </div>

      {/* Navigation */}
      <nav className="sidebar__nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.view}
            className={`nav-item${view === item.view ? " active" : ""}`}
            onClick={() => onView(item.view)}
          >
            <span className="icon">{item.icon}</span>
            <div>
              <div style={{ lineHeight: 1.3 }}>{item.label}</div>
              <div style={{ fontSize: 10, color: "var(--text-3)", lineHeight: 1.2 }}>{item.sub}</div>
            </div>
          </button>
        ))}
      </nav>

      <div className="sidebar__divider" />

      {/* Conversations */}
      {view === "chat" && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 var(--lg)" }}>
            <span className="sidebar__section-label">对话</span>
            <button
              onClick={onNew}
              style={{ fontSize: 18, color: "var(--text-3)", lineHeight: 1, padding: "2px 4px", borderRadius: "var(--r-xs)" }}
              title="新建对话"
            >
              +
            </button>
          </div>
          <div className="sidebar__conversations">
            {conversations.length === 0 ? (
              <div style={{ padding: "var(--lg)", fontSize: 12, color: "var(--text-3)", textAlign: "center" }}>
                暂无对话
              </div>
            ) : (
              conversations.map((c) => (
                <div
                  key={c.id}
                  className={`conv-item${c.id === activeId ? " active" : ""}`}
                  onClick={() => onSelect(c.id)}
                >
                  <span className="conv-item__title">
                    {c.title || "新对话"}
                  </span>
                  <button
                    className="conv-item__delete"
                    onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
                    title="删除"
                  >
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}

      <div style={{ flex: 1 }} />

      {/* Agent status footer */}
      <div className="agent-footer" onClick={onAgentClick} title="点击前往设置">
        {(["A1", "A2", "A3", "A4"] as const).map((label, i) => {
          const state = i < 3
            ? (health.configured ? "ready" : "unconfigured")
            : "unconfigured";
          return (
            <div key={label} className="agent-dot">
              <div className={`agent-dot__pip ${state}`} />
              <span className="agent-dot__label">{label}</span>
            </div>
          );
        })}
        <div style={{ marginLeft: "auto", fontSize: 12, color: "var(--text-3)" }}>⚙</div>
      </div>
    </aside>
  );
}

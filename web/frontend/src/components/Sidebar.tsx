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
  onClose: () => void;
}

const NAV_ITEMS: Array<{ view: View; icon: string; label: string; sub: string }> = [
  { view: "chat",      icon: "◎", label: "协作",    sub: "对话与任务" },
  { view: "workspace", icon: "⬡", label: "能力域",   sub: "Terr 管理" },
  { view: "memory",    icon: "◈", label: "记忆",    sub: "Mom1/2/3" },
  { view: "settings",  icon: "≡", label: "设置",    sub: "模型与服务器" },
];

function healthColor(h: HealthStatus): string {
  if (h.status === "ok" && h.configured) return "var(--success)";
  if (h.status === "ok") return "var(--warning)";
  if (h.status === "error") return "var(--danger)";
  return "var(--muted)";
}

export function Sidebar({
  view, onView, conversations, activeId, onSelect, onNew, onDelete, health, onAgentClick, onClose,
}: Props) {
  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar__header">
        <img src="/icon.png" className="sidebar__logo" alt="Qcowork" />
        <span className="sidebar__title">Qcowork</span>
        <button className="sidebar__close" onClick={onClose} aria-label="关闭导航">×</button>
        <div
          className="sidebar__health"
          style={{ background: healthColor(health) }}
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
            <div className="nav-item__copy">
              <div className="nav-item__label">{item.label}</div>
              <div className="nav-item__sub">{item.sub}</div>
            </div>
          </button>
        ))}
      </nav>

      <div className="sidebar__divider" />

      {/* Conversations */}
      {view === "chat" && (
        <>
          <div className="sidebar__section-head">
            <span className="sidebar__section-label">对话</span>
            <button
              onClick={onNew}
              className="sidebar__new"
              title="新建对话"
            >
              +
            </button>
          </div>
          <div className="sidebar__conversations">
            {conversations.length === 0 ? (
              <div className="sidebar__empty">
                暂无对话
              </div>
            ) : (
              conversations.map((c) => (
                <div
                  key={c.id}
                  className={`conv-item${c.id === activeId ? " active" : ""}`}
                >
                  <button className="conv-item__open" onClick={() => onSelect(c.id)}>
                    <span className="conv-item__title">
                      {c.title || "新对话"}
                    </span>
                  </button>
                  <button
                    className="conv-item__delete"
                    onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
                    title="删除"
                    aria-label={`删除${c.title || "新对话"}`}
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        </>
      )}

      <div className="sidebar__spacer" />

      {/* Agent status footer */}
      <button className="agent-footer" onClick={onAgentClick} title="点击前往设置">
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
        <div className="agent-footer__settings">设置</div>
      </button>
    </aside>
  );
}

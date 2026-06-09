import { useCallback, useEffect, useRef, useState } from "react";
import * as client from "./api/client";
import { ChatView } from "./components/ChatView";
import { MemoryPanel } from "./components/MemoryPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { Sidebar } from "./components/Sidebar";
import { TerrPanel } from "./components/TerrPanel";
import type { Conversation, HealthStatus, Message, Settings } from "./types";
import { DEFAULT_SETTINGS } from "./types";

// ── Persistence helpers ───────────────────────────────────────────────────────

const SETTINGS_KEY = "autumn.settings";
const CONVOS_KEY = "autumn.conversations";

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(s: Settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVOS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveConversations(cs: Conversation[]) {
  localStorage.setItem(CONVOS_KEY, JSON.stringify(cs));
}

function newConversation(): Conversation {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    title: "",
    createdAt: Date.now(),
    messages: [],
  };
}

// ── App ───────────────────────────────────────────────────────────────────────

type View = "chat" | "workspace" | "memory" | "settings";

export function App() {
  const [view, setView] = useState<View>("chat");
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const cs = loadConversations();
    return cs.length > 0 ? cs : [newConversation()];
  });
  const [activeId, setActiveId] = useState<string>(() => {
    const cs = loadConversations();
    return cs[0]?.id ?? newConversation().id;
  });
  const [health, setHealth] = useState<HealthStatus>({ status: "unchecked", configured: false });
  const [error, setError] = useState("");
  const healthTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persist on change.
  useEffect(() => { saveSettings(settings); }, [settings]);
  useEffect(() => { saveConversations(conversations); }, [conversations]);

  // Poll health every 30s.
  useEffect(() => {
    async function check() {
      try {
        const h = await client.getHealth(settings);
        setHealth({ status: h.status as "ok" | "error", configured: h.configured, last_error: h.last_error });
      } catch {
        setHealth({ status: "error", configured: false });
      }
    }
    check();
    healthTimerRef.current = setInterval(check, 30_000);
    return () => { if (healthTimerRef.current) clearInterval(healthTimerRef.current); };
    // eslint-disable-next-line
  }, [settings.serverUrl, settings.authToken]);

  const activeConversation = conversations.find((c) => c.id === activeId) ?? conversations[0];

  function updateConversation(update: Partial<Conversation> & { id: string }) {
    setConversations((cs) =>
      cs.map((c) => c.id === update.id ? { ...c, ...update } : c)
    );
  }

  function createConversation() {
    const c = newConversation();
    setConversations((cs) => [c, ...cs]);
    setActiveId(c.id);
    setView("chat");
  }

  function deleteConversation(id: string) {
    setConversations((cs) => {
      const next = cs.filter((c) => c.id !== id);
      if (next.length === 0) {
        const fresh = newConversation();
        setActiveId(fresh.id);
        return [fresh];
      }
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  const handleError = useCallback((err: string) => setError(err), []);

  return (
    <div className="app">
      <Sidebar
        view={view}
        onView={setView}
        conversations={[...conversations].sort((a, b) => b.createdAt - a.createdAt)}
        activeId={activeId}
        onSelect={(id) => { setActiveId(id); setView("chat"); }}
        onNew={createConversation}
        onDelete={deleteConversation}
        health={health}
        onAgentClick={() => setView("settings")}
      />

      <main className="main">
        {error && (
          <div className="error-banner">
            <span>⚠ {error}</span>
            <button className="error-banner__close btn" onClick={() => setError("")}>✕</button>
          </div>
        )}

        {view === "chat" && activeConversation && (
          <ChatView
            key={activeConversation.id}
            conversation={activeConversation}
            settings={settings}
            onUpdateConversation={updateConversation}
            onError={handleError}
          />
        )}

        {view === "workspace" && (
          <TerrPanel settings={settings} />
        )}

        {view === "memory" && (
          <MemoryPanel settings={settings} />
        )}

        {view === "settings" && (
          <SettingsPanel settings={settings} onChange={setSettings} />
        )}
      </main>
    </div>
  );
}

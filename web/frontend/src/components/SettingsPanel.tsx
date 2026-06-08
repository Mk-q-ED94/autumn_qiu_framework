import { useEffect, useState } from "react";
import * as client from "../api/client";
import { DEFAULT_OLLAMA_URL } from "../types";
import type { Protocol, Settings, SlotConfig } from "../types";
import { OllamaManager } from "./OllamaManager";

type Tab = "server" | "models" | "advanced";

interface Props {
  settings: Settings;
  onChange: (s: Settings) => void;
}

// ── Slot config row ───────────────────────────────────────────────────────────

function SlotCard({
  label,
  slot,
  settings,
  onChange,
  optional = false,
  enabled = true,
  onToggle,
}: {
  label: string;
  slot: SlotConfig;
  settings: Settings;
  onChange: (s: SlotConfig) => void;
  optional?: boolean;
  enabled?: boolean;
  onToggle?: (on: boolean) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);

  async function fetchModels() {
    if (!slot.api_key || !slot.base_url) return;
    setFetching(true);
    try {
      const ms = await client.getModels(settings, slot);
      setModels(ms);
    } catch {
      // silent
    } finally {
      setFetching(false);
    }
  }

  function update(patch: Partial<SlotConfig>) {
    onChange({ ...slot, ...patch });
  }

  const slotColor: Record<string, string> = {
    A1: "var(--wp1)", A2: "var(--wp2)", A3: "var(--wp3)", A4: "var(--muted)",
  };

  return (
    <div className="slot-card" style={{ opacity: optional && !enabled ? 0.55 : 1 }}>
      <div className="slot-card__header">
        <div style={{ display: "flex", alignItems: "center", gap: "var(--sm)" }}>
          <span
            style={{
              width: 22, height: 22,
              borderRadius: "var(--r-sm)",
              background: slotColor[label] ?? "var(--surface-elevated)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, fontWeight: 700, color: "#fff",
              flexShrink: 0,
            }}
          >
            {label}
          </span>
          <span className="slot-card__label">{label}</span>
        </div>
        {optional && onToggle && (
          <button
            className={`terr-toggle${enabled ? " on" : ""}`}
            onClick={() => onToggle(!enabled)}
            title={enabled ? "禁用" : "启用"}
          >
            <div className="terr-toggle__pip" />
          </button>
        )}
      </div>

      {(!optional || enabled) && (
        <div className="slot-card__grid">
          <div className="field">
            <label>API Key</label>
            <input
              type="password"
              value={slot.api_key}
              onChange={(e) => update({ api_key: e.target.value })}
              placeholder="sk-…"
              autoComplete="off"
            />
          </div>
          <div className="field">
            <label>协议</label>
            <select
              value={slot.protocol}
              onChange={(e) => update({ protocol: e.target.value as Protocol })}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </div>
          <div className="field span-2">
            <label>Base URL</label>
            <input
              type="text"
              value={slot.base_url}
              onChange={(e) => update({ base_url: e.target.value })}
              placeholder="https://api.openai.com"
            />
          </div>
          <div className="field span-2">
            <label>模型</label>
            <div style={{ display: "flex", gap: "var(--sm)" }}>
              {models.length > 0 ? (
                <select
                  style={{ flex: 1 }}
                  value={slot.model}
                  onChange={(e) => update({ model: e.target.value })}
                >
                  <option value="">选择模型…</option>
                  {models.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  style={{ flex: 1 }}
                  value={slot.model}
                  onChange={(e) => update({ model: e.target.value })}
                  placeholder="gpt-4o-mini"
                />
              )}
              <button
                className="btn btn--secondary"
                style={{ padding: "6px 10px", fontSize: 11 }}
                onClick={fetchModels}
                disabled={fetching}
                title="拉取模型列表"
              >
                {fetching ? <span className="spinner spinner--sm" /> : "拉取"}
              </button>
            </div>
          </div>
          <div className="field span-2">
            <label>
              定价（可选，USD / 1M tokens）<span className="field__hint" style={{ marginLeft: 6 }}>填写后 trace 显示每轮费用</span>
            </label>
            <div style={{ display: "flex", gap: "var(--sm)" }}>
              <input
                type="number"
                min={0}
                step="0.01"
                style={{ flex: 1 }}
                value={slot.input_price_per_1m ?? ""}
                onChange={(e) =>
                  update({ input_price_per_1m: e.target.value === "" ? undefined : Number(e.target.value) })
                }
                placeholder="输入价 ↑"
              />
              <input
                type="number"
                min={0}
                step="0.01"
                style={{ flex: 1 }}
                value={slot.output_price_per_1m ?? ""}
                onChange={(e) =>
                  update({ output_price_per_1m: e.target.value === "" ? undefined : Number(e.target.value) })
                }
                placeholder="输出价 ↓"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SettingsPanel({ settings, onChange }: Props) {
  const [tab, setTab] = useState<Tab>("server");
  const [health, setHealth] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: "" });
  const [checking, setChecking] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyMsg, setApplyMsg] = useState("");
  const [a4Enabled, setA4Enabled] = useState(!!settings.a4?.api_key);
  const [ollamaUrl, setOllamaUrl] = useState(settings.a4?.base_url || DEFAULT_OLLAMA_URL);

  useEffect(() => {
    checkHealth();
    // eslint-disable-next-line
  }, []);

  async function checkHealth() {
    setChecking(true);
    try {
      const h = await client.getHealth(settings);
      setHealth({
        ok: h.status === "ok",
        msg: h.configured ? "已配置，服务就绪" : "服务在线但尚未配置模型",
      });
    } catch (e) {
      setHealth({ ok: false, msg: `连接失败: ${e}` });
    } finally {
      setChecking(false);
    }
  }

  async function applyConfig() {
    setApplying(true);
    setApplyMsg("");
    try {
      await client.applyConfig(settings);
      setApplyMsg("✓ 配置已应用");
      await checkHealth();
    } catch (e) {
      setApplyMsg(`✗ ${e}`);
    } finally {
      setApplying(false);
    }
  }

  function updateSlot(slot: "a1" | "a2" | "a3" | "a4") {
    return (v: SlotConfig) => onChange({ ...settings, [slot]: v });
  }

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: "server", label: "服务器" },
    { id: "models", label: "模型" },
    { id: "advanced", label: "高级" },
  ];

  return (
    <div className="panel">
      <div className="panel__header">
        <h2>设置</h2>
        <div className="tab-pills">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab-pill${tab === t.id ? " active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="panel__body">
        {/* ── 服务器 tab ── */}
        {tab === "server" && (
          <>
            <div className="settings-section">
              <div className="settings-section__title">连接</div>
              <div className="health-indicator">
                <div className={`health-dot ${health.ok ? "ok" : "error"}`} />
                <span>{health.msg || "未检查"}</span>
                <button
                  className="btn btn--secondary"
                  style={{ marginLeft: "auto", padding: "4px 10px", fontSize: 11 }}
                  onClick={checkHealth}
                  disabled={checking}
                >
                  {checking ? <span className="spinner spinner--sm" /> : "检测"}
                </button>
              </div>

              <div className="field">
                <label>服务器 URL（通过 Worker 代理时填 /api）</label>
                <input
                  type="text"
                  value={settings.serverUrl}
                  onChange={(e) => onChange({ ...settings, serverUrl: e.target.value })}
                  placeholder="/api"
                />
                <span className="field__hint">
                  Cloudflare 部署: <code>/api</code>；本地调试: <code>http://127.0.0.1:8765</code>
                </span>
              </div>

              <div className="field">
                <label>Auth Token（对应 Worker 的 AUTH_TOKEN 密钥）</label>
                <input
                  type="password"
                  value={settings.authToken}
                  onChange={(e) => onChange({ ...settings, authToken: e.target.value })}
                  placeholder="留空则不认证"
                  autoComplete="off"
                />
              </div>
            </div>

            <div className="settings-section">
              <div className="settings-section__title">会话</div>
              <button
                className="btn btn--danger"
                onClick={async () => {
                  await client.endSession(settings);
                  alert("会话已结束，短期记忆已清除。");
                }}
              >
                结束会话（清空短期记忆）
              </button>
            </div>
          </>
        )}

        {/* ── 模型 tab ── */}
        {tab === "models" && (
          <>
            <SlotCard label="A1" slot={settings.a1} settings={settings} onChange={updateSlot("a1")} />
            <SlotCard label="A2" slot={settings.a2} settings={settings} onChange={updateSlot("a2")} />
            <SlotCard label="A3" slot={settings.a3} settings={settings} onChange={updateSlot("a3")} />
            <SlotCard
              label="A4"
              slot={settings.a4 ?? { api_key: "", base_url: "http://localhost:11434", model: "", protocol: "openai" }}
              settings={settings}
              onChange={updateSlot("a4")}
              optional
              enabled={a4Enabled}
              onToggle={(on) => {
                setA4Enabled(on);
                if (!on) onChange({ ...settings, a4: undefined });
              }}
            />

            {a4Enabled && (
              <OllamaManager
                settings={settings}
                ollamaUrl={ollamaUrl}
                onUrlChange={setOllamaUrl}
                currentA4Model={settings.a4?.model}
                onSelectModel={(name, baseUrl) => {
                  // One-click wire: a local Ollama model needs only a dummy key
                  // (Ollama ignores it) and the OpenAI-compat protocol.
                  onChange({
                    ...settings,
                    a4: { api_key: "ollama", base_url: baseUrl, model: name, protocol: "openai" },
                  });
                  setA4Enabled(true);
                }}
              />
            )}

            <div style={{ display: "flex", alignItems: "center", gap: "var(--md)" }}>
              <button className="btn btn--primary" onClick={applyConfig} disabled={applying}>
                {applying ? <span className="spinner spinner--sm" style={{ borderTopColor: "#fff" }} /> : "应用配置"}
              </button>
              {applyMsg && (
                <span style={{ fontSize: 12, color: applyMsg.startsWith("✓") ? "var(--success)" : "var(--danger)" }}>
                  {applyMsg}
                </span>
              )}
            </div>
          </>
        )}

        {/* ── 高级 tab ── */}
        {tab === "advanced" && (
          <div className="settings-section">
            <div className="settings-section__title">关于</div>
            <div style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", padding: "var(--lg)" }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: "var(--sm)" }}>秋 / Autumn 0.1.0</div>
              <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.6 }}>
                多模型协作工作流框架。A1 分类路由，A2 执行任务，A3 处理 Mission，Mom1/2/3 提供分层记忆。
                <br />
                <br />
                Cloudflare 部署：前端 Pages + Worker BFF + Python Container。
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

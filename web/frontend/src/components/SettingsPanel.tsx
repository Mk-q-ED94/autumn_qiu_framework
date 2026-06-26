import { useEffect, useState } from "react";
import * as client from "../api/client";
import { DEFAULT_OLLAMA_URL } from "../types";
import type { FourDStatus, Protocol, ServerMetrics, Settings, SlotConfig } from "../types";
import { OllamaManager } from "./OllamaManager";

type Tab = "server" | "models" | "advanced";

interface Props {
  settings: Settings;
  onChange: (s: Settings) => void;
}

// ── /metrics widget ───────────────────────────────────────────────────────────

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)} K`;
  return String(n);
}

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function MetricsWidget({ settings }: { settings: Settings }) {
  const [data, setData] = useState<ServerMetrics | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    client
      .getMetrics(settings)
      .then((m) => alive && setData(m))
      .catch(() => alive && setErr("无法获取服务器指标"));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (err) return <div className="field__hint field__hint--error">{err}</div>;
  if (!data) return <div className="field__hint">指标加载中…</div>;

  const cells: Array<{ label: string; value: string; danger?: boolean }> = [
    { label: "累计运行", value: String(data.runs) },
    { label: "错误数", value: String(data.errors), danger: data.errors > 0 },
    { label: "输入 Token", value: fmtTokens(data.prompt_tokens) },
    { label: "输出 Token", value: fmtTokens(data.completion_tokens) },
    { label: "运行时长", value: fmtUptime(data.uptime_seconds) },
  ];

  return (
    <div className="about-card__metrics">
      {cells.map((c) => (
        <div key={c.label} className="about-metrics-cell">
          <div className="about-metrics-cell__label">{c.label}</div>
          <div className={`about-metrics-cell__value${c.danger ? " about-metrics-cell__value--error" : ""}`}>
            {c.value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── 4D memory runtime flags ───────────────────────────────────────────────────

const FOURD_ROWS: Array<{ key: keyof FourDStatus; label: string; hint: string }> = [
  { key: "fourd_memory_enabled", label: "4D 激活排序", hint: "按目的 / 使用 / 时间维度对召回与淘汰排序" },
  { key: "fourd_push_on_turn", label: "回合开始推入", hint: "每轮开始时注入 CONSTRAIN / REMIND 记忆" },
  { key: "fourd_pull_on_turn", label: "回合开始召回", hint: "每轮把 Mom1 跨轮对话上下文拉入执行器" },
  { key: "fourd_auto_annotate", label: "自动标注维度", hint: "每轮后由 A4 自动为新写入的 Mom1 条目标注 aim/use/trigger 维度（需要 A4）" },
  { key: "fourd_auto_consolidate", label: "自动整合记忆", hint: "Mom1 接近上限时由 A4 自动整合为摘要条目（需要 A4）" },
  { key: "fourd_auto_evolve", label: "自动自进化", hint: "会话记忆充足时由 A4 将高频有用模式提炼为固定技能（默认关闭，属有意为之）" },
  { key: "mom1_access_enabled", label: "Mom1 受控访问", hint: "允许 Mom2 / Mom3 经 A1 裁决读取 Mom1" },
];

function FourDSettings({ settings }: { settings: Settings }) {
  const [status, setStatus] = useState<FourDStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    client
      .getFourDStatus(settings)
      .then((s) => alive && setStatus(s))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggle(key: keyof FourDStatus) {
    if (!status || busy) return;
    const previous = status;
    const next = { ...status, [key]: !status[key] };
    setStatus(next); // optimistic
    setBusy(true);
    setErr("");
    try {
      setStatus(await client.setFourDConfig(settings, { [key]: next[key] }));
    } catch (e) {
      setStatus(previous); // rollback
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-section">
      <div className="settings-section__title">4D 记忆引擎</div>
      {!status && !err && <div className="field__hint">加载中…</div>}
      {err && <div className="field__hint field__hint--error">{err}</div>}
      {status &&
        FOURD_ROWS.map((r) => (
          <div key={r.key} className="fourd-row">
            <div>
              <div className="fourd-row__label">{r.label}</div>
              <div className="field__hint">{r.hint}</div>
            </div>
            <button
              className={`terr-toggle${status[r.key] ? " on" : ""}`}
              onClick={() => toggle(r.key)}
              disabled={busy}
              title={status[r.key] ? "关闭" : "开启"}
            >
              <div className="terr-toggle__pip" />
            </button>
          </div>
        ))}
    </div>
  );
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

  return (
    <div className={`slot-card${optional && !enabled ? " disabled" : ""}`}>
      <div className="slot-card__header">
        <div className="slot-card__identity">
          <span className={`slot-card__badge ${label.toLowerCase()}`}>
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
            <div className="field-inline">
              {models.length > 0 ? (
                <select
                  className="field-grow"
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
                  className="field-grow"
                  value={slot.model}
                  onChange={(e) => update({ model: e.target.value })}
                  placeholder="gpt-4o-mini"
                />
              )}
              <button
                className="btn btn--secondary btn--compact"
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
              定价（可选，USD / 1M tokens）<span className="field__hint field__hint--inline">填写后 trace 显示每轮费用</span>
            </label>
            <div className="field-inline">
              <input
                type="number"
                min={0}
                step="0.01"
                className="field-grow"
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
                className="field-grow"
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
      setHealth({ ok: false, msg: `连接失败: ${e instanceof Error ? e.message : e}` });
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
      setApplyMsg(`✗ ${e instanceof Error ? e.message : e}`);
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
                  className="btn btn--secondary btn--compact btn--right"
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

            <div className="settings-actions">
              <button className="btn btn--primary" onClick={applyConfig} disabled={applying}>
                {applying ? <span className="spinner spinner--sm spinner--inverse" /> : "应用配置"}
              </button>
              {applyMsg && (
                <span className={`settings-actions__message ${applyMsg.startsWith("✓") ? "success" : "danger"}`}>
                  {applyMsg}
                </span>
              )}
            </div>
          </>
        )}

        {/* ── 高级 tab ── */}
        {tab === "advanced" && (
          <>
            <FourDSettings settings={settings} />
            <div className="settings-section">
              <div className="settings-section__title">关于</div>
              <div className="about-card">
                <div className="about-card__title">Qcowork 0.3.4</div>
                <div className="about-card__body">
                  多模型协作工作流框架。A1 组长分类、规划并监督，A2 执行任务，A3 处理 Mission，A4 管理 4D 记忆（Mom1/2/3 + shared）。
                  <br />
                  <br />
                  Cloudflare 部署：前端 Pages + Worker BFF + Python Container。
                </div>
                <MetricsWidget settings={settings} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

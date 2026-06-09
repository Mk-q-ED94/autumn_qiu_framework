import { useCallback, useEffect, useRef, useState } from "react";
import * as client from "../api/client";
import type { Conversation, IntentPreview, Message, MissionRoute, Settings } from "../types";
import { ComposerBar } from "./ComposerBar";
import { PipelineStrip } from "./PipelineStrip";

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  return (
    <div className={`message message--${message.role}`}>
      <div className="message__bubble">
        {message.content}
        {message.isStreaming && <span className="message__cursor" />}
      </div>
      {message.trace && !message.isStreaming && (
        <PipelineStrip trace={message.trace} />
      )}
      {message.isStreaming && !message.trace && (
        <div className="pipeline-strip" style={{ opacity: 0.4 }}>
          <div className="stage-capsule wp1 active">● A1</div>
          <div className="stage-connector" />
          <div className="stage-capsule wp2 pending">● WP2</div>
        </div>
      )}
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  conversation: Conversation;
  settings: Settings;
  onUpdateConversation: (update: Partial<Conversation> & { id: string }) => void;
  onError: (err: string) => void;
}

// ── Chat view ─────────────────────────────────────────────────────────────────

export function ChatView({ conversation, settings, onUpdateConversation, onError }: Props) {
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [intentPreview, setIntentPreview] = useState<IntentPreview | null>(null);
  const [intentLoading, setIntentLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const intentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom when messages change.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation.messages]);

  // Debounced intent preview on every keystroke.
  const scheduleIntent = useCallback(
    (text: string) => {
      if (intentTimerRef.current) clearTimeout(intentTimerRef.current);
      if (!text.trim() || text.length < 4) {
        setIntentPreview(null);
        return;
      }
      setIntentLoading(true);
      intentTimerRef.current = setTimeout(async () => {
        try {
          const preview = await client.classifyIntent(settings, text);
          setIntentPreview(preview);
        } catch {
          // silent — intent preview is advisory
        } finally {
          setIntentLoading(false);
        }
      }, 350);
    },
    [settings]
  );

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    scheduleIntent(e.target.value);
    // Auto-grow
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }

  function newMsgId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    setIntentPreview(null);
    setIsStreaming(true);

    const userMsg: Message = { id: newMsgId(), role: "user", content: text };
    const assistantMsgId = newMsgId();
    const assistantMsg: Message = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    const updatedMessages = [...conversation.messages, userMsg, assistantMsg];

    // Derive title from first message
    const title =
      conversation.title ||
      text.slice(0, 40) + (text.length > 40 ? "…" : "");

    onUpdateConversation({ id: conversation.id, messages: updatedMessages, title });

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      let accumulated = "";
      for await (const event of client.streamChat(settings, text, undefined, undefined, abort.signal)) {
        if ("chunk" in event) {
          accumulated += event.chunk;
          onUpdateConversation({
            id: conversation.id,
            messages: updatedMessages.map((m) =>
              m.id === assistantMsgId ? { ...m, content: accumulated } : m
            ),
          });
        } else if ("trace" in event) {
          // Final trace — attach to message and stop streaming indicator.
          onUpdateConversation({
            id: conversation.id,
            messages: updatedMessages.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: event.trace.output, trace: event.trace, isStreaming: false }
                : m
            ),
          });
        } else if ("error" in event) {
          onError(event.error);
          onUpdateConversation({
            id: conversation.id,
            messages: updatedMessages.map((m) =>
              m.id === assistantMsgId ? { ...m, isStreaming: false } : m
            ),
          });
        }
      }

      // If stream ended without a trace event (e.g. non-trace stream path),
      // just stop the streaming cursor.
      onUpdateConversation({
        id: conversation.id,
        messages: (updatedMessages).map((m) =>
          m.id === assistantMsgId && m.isStreaming
            ? { ...m, isStreaming: false }
            : m
        ),
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        onError(String(err));
        onUpdateConversation({
          id: conversation.id,
          messages: updatedMessages.map((m) =>
            m.id === assistantMsgId ? { ...m, isStreaming: false } : m
          ),
        });
      }
    } finally {
      setIsStreaming(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleStop() {
    abortRef.current?.abort();
    setIsStreaming(false);
  }

  return (
    <div className="chat-view">
      {/* Header */}
      <div className="chat-header">
        <span className="chat-header__title">{conversation.title || "新对话"}</span>
        <div className="chat-header__actions">
          {isStreaming && (
            <button className="btn btn--secondary" style={{ fontSize: 12, padding: "4px 10px" }} onClick={handleStop}>
              停止
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="messages-list">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state__icon">秋</div>
            <div className="empty-state__title">开始协作</div>
            <div className="empty-state__sub">
              输入任何问题或任务。WP1 会自动分类，WP2/WP3 协同处理后返回结果，过程在下方流水线条带中展示。
            </div>
          </div>
        ) : (
          conversation.messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Intent preview bar */}
      <ComposerBar
        preview={intentPreview}
        isLoading={intentLoading}
        onClear={() => setIntentPreview(null)}
      />

      {/* Input bar */}
      <div className="input-bar">
        <textarea
          className="input-bar__textarea"
          placeholder="输入任务或问题…（Enter 发送，Shift+Enter 换行）"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={isStreaming}
        />
        <button
          className="input-bar__send"
          onClick={handleSend}
          disabled={!input.trim() || isStreaming}
          title="发送"
        >
          {isStreaming ? (
            <span className="spinner spinner--sm" style={{ borderColor: "var(--text-3)", borderTopColor: "var(--text)" }} />
          ) : "↑"}
        </button>
      </div>
    </div>
  );
}

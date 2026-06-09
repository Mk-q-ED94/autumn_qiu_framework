import type { IntentPreview } from "../types";

interface Props {
  preview: IntentPreview | null;
  isLoading: boolean;
  onClear: () => void;
}

function confidenceClass(c: number): "high" | "medium" | "low" {
  if (c >= 0.75) return "high";
  if (c >= 0.5) return "medium";
  return "low";
}

function intentLabel(preview: IntentPreview): string {
  if (preview.input_type === "task") return "Task";
  if (preview.route === "convert") return "Mission → Task";
  return "Mission · Direct";
}

function intentClass(preview: IntentPreview): string {
  return preview.input_type === "task" ? "task" : "mission";
}

export function ComposerBar({ preview, isLoading, onClear }: Props) {
  if (!preview && !isLoading) return null;

  const isLowConf = preview ? preview.confidence < 0.5 : false;

  return (
    <div className={`composer-bar${isLowConf ? " low-confidence" : ""}`}>
      {isLoading && !preview ? (
        <div className="spinner spinner--sm" />
      ) : preview ? (
        <>
          <div className={`intent-pill ${intentClass(preview)}`}>
            {intentClass(preview) === "task" ? "⬡" : "◎"} {intentLabel(preview)}
          </div>

          <span
            className={`confidence-chip ${confidenceClass(preview.confidence)}`}
            title={`置信度: ${(preview.confidence * 100).toFixed(0)}%`}
          >
            {(preview.confidence * 100).toFixed(0)}%
          </span>

          {preview.reasoning && (
            <span className="composer-bar__reasoning" title={preview.reasoning}>
              {preview.reasoning}
            </span>
          )}

          <button className="composer-bar__clear" onClick={onClear} title="清除预测">
            ↩
          </button>
        </>
      ) : null}
    </div>
  );
}

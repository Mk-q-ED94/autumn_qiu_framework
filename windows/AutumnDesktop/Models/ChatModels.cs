using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Serialization;

namespace AutumnDesktop.Models;

// These records mirror the FastAPI wire contract one-to-one with the macOS
// app's ChatModels.swift. snake_case on the wire ↔ PascalCase in C# via
// [JsonPropertyName]. Keep in sync with autumn/server/app.py.

public sealed record ProcessRequest(
    [property: JsonPropertyName("input")] string Input,
    [property: JsonPropertyName("route")] string? Route = null,
    [property: JsonPropertyName("input_type")] string? InputType = null,
    [property: JsonPropertyName("task_type")] string? TaskType = null,
    [property: JsonPropertyName("project_instructions")] string? ProjectInstructions = null,
    [property: JsonPropertyName("project_id")] string? ProjectId = null);

public sealed record ProcessResponse(
    [property: JsonPropertyName("output")] string Output);

public sealed record WorkflowStage(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("title")] string Title,
    [property: JsonPropertyName("detail")] string Detail,
    [property: JsonPropertyName("workspace")] string Workspace,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("kind")] string? Kind = "stage",
    [property: JsonPropertyName("duration_ms")] double? DurationMs = null,
    [property: JsonPropertyName("prompt_tokens")] int? PromptTokens = null,
    [property: JsonPropertyName("completion_tokens")] int? CompletionTokens = null,
    [property: JsonPropertyName("source_terr")] string? SourceTerr = null,
    [property: JsonPropertyName("cost_usd")] double? CostUsd = null)
{
    [JsonIgnore] public string KindOrStage => string.IsNullOrEmpty(Kind) ? "stage" : Kind!;

    /// <summary>Upper-cased workspace label for the trace row ("WP1"…).</summary>
    [JsonIgnore] public string WorkspaceLabel => (Workspace ?? "").ToUpperInvariant();

    /// <summary>Duration + token metrics, pre-formatted for the trace row.</summary>
    [JsonIgnore]
    public string MetaLine
    {
        get
        {
            var parts = new System.Collections.Generic.List<string>();
            var dur = DesignSystem.Autumn.Format.Duration(DurationMs);
            if (dur.Length > 0) parts.Add(dur);
            var tok = DesignSystem.Autumn.Format.Tokens(PromptTokens, CompletionTokens);
            if (tok.Length > 0) parts.Add(tok);
            var cost = DesignSystem.Autumn.Format.Cost(CostUsd);
            if (cost.Length > 0) parts.Add(cost);
            return string.Join("   ·   ", parts);
        }
    }

    [JsonIgnore] public Microsoft.UI.Xaml.Visibility MetaVisibility =>
        MetaLine.Length > 0 ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    [JsonIgnore] public Microsoft.UI.Xaml.Visibility DetailVisibility =>
        string.IsNullOrWhiteSpace(Detail) ? Microsoft.UI.Xaml.Visibility.Collapsed : Microsoft.UI.Xaml.Visibility.Visible;
}

public sealed record WorkflowTrace(
    [property: JsonPropertyName("output")] string Output,
    [property: JsonPropertyName("input_type")] string InputType,
    [property: JsonPropertyName("route")] string? Route,
    [property: JsonPropertyName("task_type")] string? TaskType,
    [property: JsonPropertyName("stages")] List<WorkflowStage> Stages,
    [property: JsonPropertyName("total_prompt_tokens")] int? TotalPromptTokens = null,
    [property: JsonPropertyName("total_completion_tokens")] int? TotalCompletionTokens = null,
    [property: JsonPropertyName("total_cost_usd")] double? TotalCostUsd = null)
{
    [JsonIgnore] public bool IsLive => Stages.Any(s => s.Status is "active" or "pending");
    [JsonIgnore] public bool HasFailedStage => Stages.Any(s => s.Status == "failed");
    [JsonIgnore] public int CompletedStageCount => Stages.Count(s => s.Status == "completed");
    [JsonIgnore] public int ToolStageCount => Stages.Count(s => s.KindOrStage == "tool");
    [JsonIgnore] public int AgentStageCount => Stages.Count(s => s.KindOrStage == "agent");
    [JsonIgnore] public bool HasAgentActivity => AgentStageCount > 0 || ToolStageCount > 0;

    [JsonIgnore]
    public double? TotalDurationMs
    {
        get
        {
            var values = Stages.Where(s => s.DurationMs.HasValue).Select(s => s.DurationMs!.Value).ToList();
            return values.Count == 0 ? null : values.Sum();
        }
    }

    [JsonIgnore]
    public IReadOnlyList<string> SourceTerrNames =>
        Stages.Where(s => s.SourceTerr != null).Select(s => s.SourceTerr!).Distinct().OrderBy(x => x).ToList();

    /// <summary>Compact one-line summary shown in the collapsed trace header.</summary>
    [JsonIgnore]
    public string SummaryLine
    {
        get
        {
            var parts = new List<string> { $"{CompletedStageCount}/{Stages.Count} 阶段" };
            if (ToolStageCount > 0) parts.Add($"{ToolStageCount} 工具");
            if (AgentStageCount > 0) parts.Add($"{AgentStageCount} Agent");
            var dur = DesignSystem.Autumn.Format.Duration(TotalDurationMs);
            if (dur.Length > 0) parts.Add(dur);
            return string.Join("   ·   ", parts);
        }
    }
}

public sealed record IntentPreview(
    [property: JsonPropertyName("input_type")] string InputType,
    [property: JsonPropertyName("task_type")] string? TaskType,
    [property: JsonPropertyName("route")] string? Route,
    [property: JsonPropertyName("confidence")] double Confidence,
    [property: JsonPropertyName("reasoning")] string? Reasoning);

public sealed record TerrParameter(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("required")] bool Required);

public sealed record TerrCallable(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("parameters")] List<TerrParameter> Parameters);

public sealed record TerrMCP(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("description")] string Description);

public sealed record TerrSummary(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("tools")] List<TerrCallable> Tools,
    [property: JsonPropertyName("skills")] List<TerrCallable> Skills,
    [property: JsonPropertyName("mcps")] List<TerrMCP> Mcps,
    [property: JsonPropertyName("enabled")] bool Enabled = true);

public sealed record StreamPayload(
    [property: JsonPropertyName("chunk")] string? Chunk,
    [property: JsonPropertyName("trace")] WorkflowTrace? Trace,
    [property: JsonPropertyName("error")] string? Error);

/// <summary>Discriminated stream event surfaced to the chat view-model.</summary>
public abstract record StreamEvent
{
    public sealed record Chunk(string Text) : StreamEvent;
    public sealed record Trace(WorkflowTrace Value) : StreamEvent;
}

public sealed record HealthResponse(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("configured")] bool Configured,
    [property: JsonPropertyName("last_error")] string? LastError = null);

public sealed record ProviderConfigRequest(
    [property: JsonPropertyName("api_key")] string ApiKey,
    [property: JsonPropertyName("base_url")] string BaseUrl,
    [property: JsonPropertyName("protocol")] string Protocol,
    [property: JsonPropertyName("model")] string? Model = null);

public sealed record ApplyConfigRequest(
    [property: JsonPropertyName("a1")] ProviderConfigRequest A1,
    [property: JsonPropertyName("a2")] ProviderConfigRequest A2,
    [property: JsonPropertyName("a3")] ProviderConfigRequest A3,
    [property: JsonPropertyName("a4")] ProviderConfigRequest? A4);

public sealed record ApplyConfigResponse(
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("configured")] bool Configured);

public sealed record ModelsRequest(
    [property: JsonPropertyName("api_key")] string ApiKey,
    [property: JsonPropertyName("base_url")] string BaseUrl,
    [property: JsonPropertyName("protocol")] string Protocol);

public sealed record ModelsResponse(
    [property: JsonPropertyName("models")] List<string> Models);

public sealed record TerrToggleRequest(
    [property: JsonPropertyName("enabled")] bool Enabled);

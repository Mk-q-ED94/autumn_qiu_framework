using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AutumnDesktop.Models;

namespace AutumnDesktop.Networking;

/// <summary>Typed error surfaced by <see cref="AutumnClient"/>, mirroring the macOS AutumnClientError.</summary>
public sealed class AutumnClientException : Exception
{
    public int? StatusCode { get; }
    public AutumnClientException(string message, int? statusCode = null) : base(message) => StatusCode = statusCode;
}

/// <summary>
/// Stateless HTTP/SSE client for the Autumn FastAPI bridge — the WinUI
/// counterpart of AutumnClient.swift. Every endpoint and the snake_case wire
/// contract match the macOS client exactly.
/// </summary>
public sealed class AutumnClient
{
    private readonly Uri _baseUrl;
    private readonly HttpClient _http;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };

    public AutumnClient(Uri baseUrl, string? apiKey = null)
    {
        _baseUrl = baseUrl;
        // No per-request timeout on the shared client — streaming endpoints run
        // long. Short-lived calls pass a CancellationToken with their own deadline.
        _http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        // Carry the server's shared secret (AUTUMN_API_KEY) when one is set so a
        // secured 0.3.0 server accepts our requests. Empty → no header, unchanged.
        if (!string.IsNullOrWhiteSpace(apiKey))
            _http.DefaultRequestHeaders.Add("X-API-Key", apiKey);
    }

    private Uri Url(string path) => new(_baseUrl, path);

    // ── health / config ──────────────────────────────────────────────────────

    public async Task<HealthResponse?> HealthAsync()
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            using var resp = await _http.GetAsync(Url("health"), cts.Token);
            if (resp.StatusCode != HttpStatusCode.OK) return null;
            return await resp.Content.ReadFromJsonAsync<HealthResponse>(JsonOpts, cts.Token);
        }
        catch
        {
            return null;
        }
    }

    public async Task<List<string>> FetchModelsAsync(string apiKey, string baseUrl, string protocol)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        var body = new ModelsRequest(apiKey, baseUrl, protocol);
        using var resp = await _http.PostAsJsonAsync(Url("models"), body, JsonOpts, cts.Token);
        await EnsureOkAsync(resp);
        var parsed = await resp.Content.ReadFromJsonAsync<ModelsResponse>(JsonOpts, cts.Token);
        return parsed?.Models ?? new List<string>();
    }

    public async Task<ApplyConfigResponse> ApplyConfigurationAsync(ApplyConfigRequest config)
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        using var resp = await _http.PostAsJsonAsync(Url("config/apply"), config, JsonOpts, cts.Token);
        await EnsureOkAsync(resp);
        return (await resp.Content.ReadFromJsonAsync<ApplyConfigResponse>(JsonOpts, cts.Token))!;
    }

    // ── synchronous execution ────────────────────────────────────────────────

    public async Task<string> ProcessAsync(ProcessRequest request, CancellationToken ct = default)
    {
        using var resp = await _http.PostAsJsonAsync(Url("process"), request, JsonOpts, ct);
        await EnsureOkAsync(resp);
        var parsed = await resp.Content.ReadFromJsonAsync<ProcessResponse>(JsonOpts, ct);
        return parsed?.Output ?? "";
    }

    public async Task<WorkflowTrace> TraceAsync(ProcessRequest request, CancellationToken ct = default)
    {
        using var linked = LinkedTimeout(ct, TimeSpan.FromSeconds(300));
        using var resp = await _http.PostAsJsonAsync(Url("trace"), request, JsonOpts, linked.Token);
        await EnsureOkAsync(resp);
        return (await resp.Content.ReadFromJsonAsync<WorkflowTrace>(JsonOpts, linked.Token))!;
    }

    public async Task<IntentPreview> PreviewIntentAsync(ProcessRequest request, CancellationToken ct = default)
    {
        using var linked = LinkedTimeout(ct, TimeSpan.FromSeconds(45));
        using var resp = await _http.PostAsJsonAsync(Url("intent"), request, JsonOpts, linked.Token);
        await EnsureOkAsync(resp);
        return (await resp.Content.ReadFromJsonAsync<IntentPreview>(JsonOpts, linked.Token))!;
    }

    // ── SSE streaming ─────────────────────────────────────────────────────────

    /// <summary>
    /// Stream a response as Server-Sent Events. Yields <see cref="StreamEvent.Chunk"/>
    /// items as tokens arrive and a final <see cref="StreamEvent.Trace"/>; throws
    /// <see cref="AutumnClientException"/> if the server emits an error event.
    /// </summary>
    public async IAsyncEnumerable<StreamEvent> StreamAsync(
        ProcessRequest request,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var query = new List<string> { $"input={Uri.EscapeDataString(request.Input)}" };
        if (request.Route is { } r) query.Add($"route={Uri.EscapeDataString(r)}");
        if (request.InputType is { } it) query.Add($"input_type={Uri.EscapeDataString(it)}");
        if (request.TaskType is { } tt) query.Add($"task_type={Uri.EscapeDataString(tt)}");
        if (!string.IsNullOrEmpty(request.ProjectInstructions))
            query.Add($"project_instructions={Uri.EscapeDataString(request.ProjectInstructions!)}");
        if (!string.IsNullOrEmpty(request.ProjectId))
            query.Add($"project_id={Uri.EscapeDataString(request.ProjectId!)}");

        var uri = new UriBuilder(Url("stream")) { Query = string.Join("&", query) }.Uri;
        using var msg = new HttpRequestMessage(HttpMethod.Get, uri);
        msg.Headers.Accept.ParseAdd("text/event-stream");

        using var resp = await _http.SendAsync(msg, HttpCompletionOption.ResponseHeadersRead, ct);
        await EnsureOkAsync(resp);

        await using var stream = await resp.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream, Encoding.UTF8);

        while (!reader.EndOfStream)
        {
            ct.ThrowIfCancellationRequested();
            var line = await reader.ReadLineAsync(ct);
            if (line is null) break;
            if (!line.StartsWith("data: ", StringComparison.Ordinal)) continue;

            var payload = line["data: ".Length..];
            if (payload == "[DONE]") yield break;

            StreamPayload? evt;
            try { evt = JsonSerializer.Deserialize<StreamPayload>(payload, JsonOpts); }
            catch { continue; }
            if (evt is null) continue;

            if (evt.Error is { Length: > 0 } err)
                throw new AutumnClientException(err);
            if (evt.Chunk is { } chunk)
                yield return new StreamEvent.Chunk(chunk);
            if (evt.Trace is { } trace)
                yield return new StreamEvent.Trace(trace);
        }
    }

    // ── terrs ─────────────────────────────────────────────────────────────────

    public async Task<List<TerrSummary>> FetchTerrsAsync(CancellationToken ct = default)
    {
        using var linked = LinkedTimeout(ct, TimeSpan.FromSeconds(20));
        using var resp = await _http.GetAsync(Url("terrs"), linked.Token);
        await EnsureOkAsync(resp);
        return (await resp.Content.ReadFromJsonAsync<List<TerrSummary>>(JsonOpts, linked.Token)) ?? new();
    }

    public async Task<TerrSummary> SetTerrEnabledAsync(string name, bool enabled, CancellationToken ct = default)
    {
        using var linked = LinkedTimeout(ct, TimeSpan.FromSeconds(20));
        using var msg = new HttpRequestMessage(HttpMethod.Patch, Url($"terrs/{Uri.EscapeDataString(name)}"))
        {
            Content = JsonContent.Create(new TerrToggleRequest(enabled), options: JsonOpts),
        };
        using var resp = await _http.SendAsync(msg, linked.Token);
        await EnsureOkAsync(resp);
        return (await resp.Content.ReadFromJsonAsync<TerrSummary>(JsonOpts, linked.Token))!;
    }

    public async Task EndSessionAsync(CancellationToken ct = default)
    {
        using var resp = await _http.PostAsync(Url("session/end"), content: null, ct);
        await EnsureOkAsync(resp);
    }

    // ── memory ────────────────────────────────────────────────────────────────

    public async Task<List<MemoryEntry>> MemoryHistoryAsync(MemoryArea area, CancellationToken ct = default)
    {
        using var linked = LinkedTimeout(ct, TimeSpan.FromSeconds(20));
        using var resp = await _http.GetAsync(Url($"memory/{area.Wire()}/history"), linked.Token);
        await EnsureOkAsync(resp);
        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync(linked.Token));
        var result = new List<MemoryEntry>();
        foreach (var element in doc.RootElement.EnumerateArray())
            result.Add(new MemoryEntry(area, element.Clone()));
        return result;
    }

    // ── error helper ──────────────────────────────────────────────────────────

    private static async Task EnsureOkAsync(HttpResponseMessage resp)
    {
        if (resp.IsSuccessStatusCode) return;
        int code = (int)resp.StatusCode;
        // FastAPI surfaces errors as {"detail": "..."} — read that when present.
        string? detail = null;
        try
        {
            var body = await resp.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("detail", out var d) &&
                d.ValueKind == JsonValueKind.String &&
                d.GetString() is { Length: > 0 } msg)
            {
                detail = msg;
            }
        }
        catch { /* non-JSON body — fall back to the status code */ }
        throw new AutumnClientException(FriendlyMessage(code, detail), code);
    }

    /// <summary>Turn a non-2xx status into actionable guidance. 0.3.0 adds 413
    /// (body too large) and enforces the optional API key (401).</summary>
    private static string FriendlyMessage(int code, string? detail) => code switch
    {
        401 => "未授权：请在「设置 · 服务器」中填写正确的 API Key。",
        413 => "输入过大：内容超出服务器请求上限，请缩短后重试。",
        502 => "上游模型出错：" + (detail ?? "请稍后重试"),
        503 => detail ?? "服务尚未配置模型，请在「设置 · 模型」中配置 A1–A3。",
        _ => detail ?? $"HTTP 状态码: {code}",
    };

    private static CancellationTokenSource LinkedTimeout(CancellationToken ct, TimeSpan timeout)
    {
        var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        return cts;
    }
}

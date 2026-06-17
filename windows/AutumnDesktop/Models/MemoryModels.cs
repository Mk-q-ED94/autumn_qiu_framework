using System.Collections.Generic;
using System.Text.Json;

namespace AutumnDesktop.Models;

/// <summary>The three layered memory areas plus the shared zone.</summary>
public enum MemoryArea
{
    Mom1,
    Mom2,
    Mom3,
    Shared,
}

public static class MemoryAreaInfo
{
    public static string Wire(this MemoryArea area) => area switch
    {
        MemoryArea.Mom1 => "mom1",
        MemoryArea.Mom2 => "mom2",
        MemoryArea.Mom3 => "mom3",
        MemoryArea.Shared => "shared",
        _ => "mom1",
    };

    public static string Title(this MemoryArea area) => area switch
    {
        MemoryArea.Mom1 => "Mom1 · 编排记忆",
        MemoryArea.Mom2 => "Mom2 · 任务记忆",
        MemoryArea.Mom3 => "Mom3 · 使命记忆",
        MemoryArea.Shared => "Shared · 共享区",
        _ => "",
    };
}

/// <summary>
/// A single memory history entry. The server returns a free-form JSON object
/// per entry, so we keep the raw element and expose convenience accessors —
/// the WinUI parallel of the macOS app's JSONValue-backed MemoryEntry.
/// </summary>
public sealed class MemoryEntry
{
    public MemoryArea Area { get; }
    public JsonElement Raw { get; }

    public MemoryEntry(MemoryArea area, JsonElement raw)
    {
        Area = area;
        Raw = raw;
    }

    public string? GetString(string key) =>
        Raw.ValueKind == JsonValueKind.Object && Raw.TryGetProperty(key, out var v)
            ? v.ValueKind == JsonValueKind.String ? v.GetString() : v.ToString()
            : null;

    public string Role => GetString("role") ?? GetString("type") ?? "entry";
    public string Content => GetString("content") ?? GetString("value") ?? GetString("text") ?? Raw.ToString();

    public IReadOnlyList<KeyValuePair<string, string>> Fields()
    {
        var list = new List<KeyValuePair<string, string>>();
        if (Raw.ValueKind != JsonValueKind.Object) return list;
        foreach (var prop in Raw.EnumerateObject())
        {
            var value = prop.Value.ValueKind == JsonValueKind.String
                ? prop.Value.GetString() ?? ""
                : prop.Value.ToString();
            list.Add(new KeyValuePair<string, string>(prop.Name, value));
        }
        return list;
    }
}

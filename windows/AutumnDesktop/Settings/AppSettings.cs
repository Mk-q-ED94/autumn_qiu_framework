using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using CommunityToolkit.Mvvm.ComponentModel;

namespace AutumnDesktop.Settings;

/// <summary>One provider slot's configuration (A1/A2/A3/A4).</summary>
public sealed partial class ProviderSettings : ObservableObject
{
    [ObservableProperty] private string _apiKey = "";
    [ObservableProperty] private string _baseUrl = "";
    [ObservableProperty] private string _model = "";
    [ObservableProperty] private string _protocol = "openai";

    public ProviderSettings Clone() => new()
    {
        ApiKey = ApiKey, BaseUrl = BaseUrl, Model = Model, Protocol = Protocol,
    };
}

/// <summary>
/// App configuration persisted as JSON under %APPDATA%\Autumn\settings.json —
/// the WinUI parallel of the macOS AppSettings (UserDefaults). A plain file is
/// used rather than ApplicationData so it works for unpackaged builds too.
/// </summary>
public sealed partial class AppSettings : ObservableObject
{
    [ObservableProperty] private string _serverUrl = "http://127.0.0.1:8765";
    // Server shared secret (AUTUMN_API_KEY). Empty → no auth header is sent.
    [ObservableProperty] private string _apiKey = "";
    [ObservableProperty] private string _missionRoute = "auto";
    [ObservableProperty] private bool _a4Enabled;

    public ProviderSettings A1 { get; set; } = new() { BaseUrl = "https://api.openai.com", Protocol = "openai" };
    public ProviderSettings A2 { get; set; } = new() { BaseUrl = "https://api.anthropic.com", Protocol = "anthropic" };
    public ProviderSettings A3 { get; set; } = new() { BaseUrl = "https://api.openai.com", Protocol = "openai" };
    public ProviderSettings A4 { get; set; } = new() { BaseUrl = "http://localhost:11434", Protocol = "openai" };

    [JsonIgnore]
    private static string FilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "Autumn", "settings.json");

    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = true };

    public static AppSettings Load()
    {
        try
        {
            if (File.Exists(FilePath))
            {
                var json = File.ReadAllText(FilePath);
                var loaded = JsonSerializer.Deserialize<AppSettings>(json, JsonOpts);
                if (loaded != null) return loaded;
            }
        }
        catch
        {
            // Corrupt/unreadable settings fall back to defaults rather than crash.
        }
        return new AppSettings();
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(this, JsonOpts));
        }
        catch
        {
            // Best-effort persistence; a failed write shouldn't break the session.
        }
    }
}

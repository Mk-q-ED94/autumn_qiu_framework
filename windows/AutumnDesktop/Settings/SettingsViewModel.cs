using System;
using System.Threading.Tasks;
using AutumnDesktop.Models;
using AutumnDesktop.Networking;
using AutumnDesktop.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace AutumnDesktop.Settings;

/// <summary>
/// Backs the settings page: persists provider config, applies it to the local
/// server, fetches model lists, and reports connection health. Mirrors the
/// macOS SettingsView/AppSettings flow.
/// </summary>
public sealed partial class SettingsViewModel : ObservableObject
{
    public AppSettings Settings => App.Settings;
    public LocalServerManager ServerManager => App.ServerManager;

    public string[] Protocols { get; } = { "openai", "anthropic" };
    public string[] Routes { get; } = { "auto", "direct", "convert" };

    [ObservableProperty] private string _connectionStatus = "未检测";
    [ObservableProperty] private string? _serverLastError;
    [ObservableProperty] private string? _applyResult;
    [ObservableProperty] private bool _isApplying;

    private static AutumnClient Client()
    {
        if (!Uri.TryCreate(App.Settings.ServerUrl, UriKind.Absolute, out var baseUrl))
            throw new AutumnClientException("服务器 URL 无效");
        return new AutumnClient(baseUrl);
    }

    [RelayCommand]
    private async Task TestConnectionAsync()
    {
        ConnectionStatus = "检测中…";
        ServerLastError = null;
        try
        {
            await ServerManager.StartIfNeededAsync(App.Settings.ServerUrl);
            var health = await Client().HealthAsync();
            if (health is null)
            {
                ConnectionStatus = "未连接";
                return;
            }
            ConnectionStatus = health.Configured ? "已连接 · 已配置" : "已连接 · 未配置";
            ServerLastError = health.LastError;
        }
        catch (Exception ex)
        {
            ConnectionStatus = "未连接";
            ServerLastError = ex.Message;
        }
    }

    [RelayCommand]
    private async Task ApplyConfigurationAsync()
    {
        IsApplying = true;
        ApplyResult = null;
        try
        {
            var request = new ApplyConfigRequest(
                A1: Provider(Settings.A1),
                A2: Provider(Settings.A2),
                A3: Provider(Settings.A3),
                A4: Settings.A4Enabled ? Provider(Settings.A4) : null);

            var resp = await Client().ApplyConfigurationAsync(request);
            ApplyResult = resp.Configured ? "已应用" : "未配置";
            Settings.Save();
        }
        catch (Exception ex)
        {
            ApplyResult = $"失败：{ex.Message}";
        }
        finally
        {
            IsApplying = false;
        }
    }

    private static ProviderConfigRequest Provider(ProviderSettings p) =>
        new(p.ApiKey, p.BaseUrl, p.Protocol, string.IsNullOrWhiteSpace(p.Model) ? null : p.Model);
}

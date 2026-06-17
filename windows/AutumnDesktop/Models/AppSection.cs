namespace AutumnDesktop.Models;

/// <summary>Top-level navigation destinations (mirrors macOS AppSection).</summary>
public enum AppSection
{
    Chat,
    Memory,
    Settings,
}

public static class AppSectionInfo
{
    public static string Title(this AppSection section) => section switch
    {
        AppSection.Chat => "协作",
        AppSection.Memory => "记忆",
        AppSection.Settings => "设置",
        _ => "",
    };

    /// <summary>Segoe Fluent Icons glyph for the nav item.</summary>
    public static string Glyph(this AppSection section) => section switch
    {
        AppSection.Chat => "",      // Message
        AppSection.Memory => "",    // History
        AppSection.Settings => "",  // Settings
        _ => "",
    };
}

/// <summary>Mission routing mode passed to the server (auto/direct/convert).</summary>
public enum MissionRouteMode
{
    Auto,
    Direct,
    Convert,
}

public static class MissionRouteModeInfo
{
    public static string Wire(this MissionRouteMode mode) => mode switch
    {
        MissionRouteMode.Direct => "direct",
        MissionRouteMode.Convert => "convert",
        _ => "auto",
    };

    public static string Title(this MissionRouteMode mode) => mode switch
    {
        MissionRouteMode.Direct => "直答",
        MissionRouteMode.Convert => "转化",
        _ => "自动",
    };
}

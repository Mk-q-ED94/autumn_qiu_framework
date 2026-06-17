using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.DesignSystem;

/// <summary>
/// Centralised design tokens — the WinUI counterpart of the macOS app's
/// <c>Tokens.swift</c>. Spacing, radii, and semantic colours live here so the
/// whole app stays visually consistent and a single edit re-themes everything.
/// XAML-level brushes/resources are defined in <c>App.xaml</c>; this class is
/// for values consumed from C# (view-models, code-behind formatting).
///
/// Design language — "Paper &amp; Clay". A calm, neutral canvas warmed by a
/// single restrained clay/terracotta accent. Hairline borders do the structural
/// work; shadows stay almost invisible. Clean system sans (Segoe UI), not
/// rounded. Mirrors <c>Tokens.swift</c> one value at a time.
/// </summary>
public static class Autumn
{
    public static class Spacing
    {
        public const double Micro = 2;
        public const double XS = 4;
        public const double S = 8;
        public const double M = 12;
        public const double L = 16;
        public const double XL = 24;
        public const double XXL = 32;
    }

    public static class Radius
    {
        public const double XS = 4;
        public const double S = 7;
        public const double M = 11;
        public const double L = 16;
        public const double XL = 22;
    }

    public static class Colors
    {
        // ── brand spine ───────────────────────────────────────────────────────
        // One warm accent — clay/terracotta — carries the whole identity. The
        // remaining hues are desaturated companions used only for semantic status
        // and the four workspace identities, never as decoration. RGB values
        // match Tokens.swift exactly.
        public static readonly Color Clay = Color.FromArgb(0xFF, 0xCC, 0x66, 0x45);     // primary accent
        public static readonly Color ClayLight = Color.FromArgb(0xFF, 0xE8, 0xA0, 0x7E); // lifted clay for dark surfaces
        public static readonly Color ClayDeep = Color.FromArgb(0xFF, 0x9C, 0x45, 0x2E); // gradient anchor
        public static readonly Color Sand = Color.FromArgb(0xFF, 0xC2, 0x9E, 0x73);     // soft warm neutral
        public static readonly Color Sage = Color.FromArgb(0xFF, 0x70, 0x8F, 0x73);     // muted green
        public static readonly Color Slate = Color.FromArgb(0xFF, 0x52, 0x7A, 0x85);    // muted blue-green
        public static readonly Color Memory = Color.FromArgb(0xFF, 0x82, 0x69, 0x9E);   // 4D / WP4 identity

        public static readonly Color Accent = Clay;

        // Status semantics — desaturated so they sit on paper without shouting.
        public static readonly Color Success = Color.FromArgb(0xFF, 0x5C, 0x99, 0x6B);
        public static readonly Color Warning = Color.FromArgb(0xFF, 0xD6, 0x94, 0x42);
        public static readonly Color Danger = Color.FromArgb(0xFF, 0xCC, 0x54, 0x4D);
        public static readonly Color Info = Slate;

        // WP1/WP2/WP3/WP4 + shared workspace tints, matching the macOS trace
        // colours: WP1=clay, WP2=warning(amber), WP3=slate, WP4=memory(violet).
        public static Color Workspace(string workspace) => (workspace ?? "").ToLowerInvariant() switch
        {
            "wp1" => Clay,
            "wp2" => Warning,
            "wp3" => Slate,
            "wp4" => Memory,
            "shared" => Slate,
            _ => Color.FromArgb(0xFF, 0x6E, 0x7B, 0x8B),
        };

        public static SolidColorBrush Brush(Color c) => new(c);
    }

    /// <summary>Shared formatters so durations/tokens/cost render identically everywhere.</summary>
    public static class Format
    {
        public static string Duration(double? ms)
        {
            if (ms is not double v) return "";
            if (v < 1000) return $"{v:0}ms";
            return $"{v / 1000.0:0.0}s";
        }

        public static string Tokens(int? prompt, int? completion)
        {
            if (prompt is null && completion is null) return "";
            int p = prompt ?? 0, c = completion ?? 0;
            return $"{p + c} tok ({p}→{c})";
        }

        public static string Cost(double? usd)
        {
            if (usd is not double v || v <= 0) return "";
            return v < 0.01 ? $"${v:0.0000}" : $"${v:0.00}";
        }
    }
}

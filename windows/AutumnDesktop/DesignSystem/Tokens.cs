using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.DesignSystem;

/// <summary>
/// Centralised design tokens — the WinUI counterpart of the macOS app's
/// <c>Tokens.swift</c>. Spacing, radii, and semantic colours live here so the
/// whole app stays visually consistent and a single edit re-themes everything.
/// XAML-level brushes/resources are defined in <c>App.xaml</c>; this class is
/// for values consumed from C# (view-models, code-behind formatting).
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
        public const double S = 8;
        public const double M = 10;
        public const double L = 14;
    }

    public static class Colors
    {
        // Autumn palette — warm accents that echo the brand banner.
        public static readonly Color Accent = Color.FromArgb(0xFF, 0xD9, 0x6B, 0x27);   // amber
        public static readonly Color Success = Color.FromArgb(0xFF, 0x4C, 0xA8, 0x66);
        public static readonly Color Warning = Color.FromArgb(0xFF, 0xE0, 0x9B, 0x2A);
        public static readonly Color Danger = Color.FromArgb(0xFF, 0xC9, 0x4B, 0x4B);

        // WP1/WP2/WP3 + shared workspace tints, matching the macOS trace colours.
        public static Color Workspace(string workspace) => workspace switch
        {
            "wp1" => Color.FromArgb(0xFF, 0x7A, 0x5C, 0xC0),  // violet — orchestration
            "wp2" => Color.FromArgb(0xFF, 0x2E, 0x86, 0xC1),  // blue — task execution
            "wp3" => Color.FromArgb(0xFF, 0xC0, 0x7A, 0x2E),  // amber — mission
            "wp4" => Color.FromArgb(0xFF, 0x4C, 0xA8, 0x66),  // green — memory curation
            "shared" => Color.FromArgb(0xFF, 0x6E, 0x7B, 0x8B), // slate — shared zone
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

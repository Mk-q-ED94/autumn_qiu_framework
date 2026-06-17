using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.DesignSystem;

/// <summary>Semantic tone for an <see cref="AutumnBadge"/> — drives its colour.</summary>
public enum BadgeTone
{
    Neutral,
    Accent,
    Success,
    Warning,
    Danger,
    Info,
    Memory,
    Sage,
}

/// <summary>
/// A small pill badge — icon + label on a tone-tinted capsule. The WinUI
/// counterpart of the macOS app's AutumnBadge: the foreground carries the tone
/// colour and the background is that colour at ~14% opacity.
/// </summary>
public sealed partial class AutumnBadge : UserControl
{
    public AutumnBadge()
    {
        InitializeComponent();
        Apply();
    }

    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(nameof(Text), typeof(string), typeof(AutumnBadge),
            new PropertyMetadata("", OnChanged));

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public static readonly DependencyProperty GlyphProperty =
        DependencyProperty.Register(nameof(Glyph), typeof(string), typeof(AutumnBadge),
            new PropertyMetadata("", OnChanged));

    /// <summary>A Segoe Fluent Icons glyph (e.g. ""); empty hides the icon.</summary>
    public string Glyph
    {
        get => (string)GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public static readonly DependencyProperty ToneProperty =
        DependencyProperty.Register(nameof(Tone), typeof(BadgeTone), typeof(AutumnBadge),
            new PropertyMetadata(BadgeTone.Neutral, OnChanged));

    public BadgeTone Tone
    {
        get => (BadgeTone)GetValue(ToneProperty);
        set => SetValue(ToneProperty, value);
    }

    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((AutumnBadge)d).Apply();

    private void Apply()
    {
        var color = ToneColor(Tone);

        // Foreground carries the tone; background is the same colour at ~14%.
        var fg = new SolidColorBrush(color);
        Root.Background = new SolidColorBrush(Color.FromArgb(0x24, color.R, color.G, color.B));
        LabelElement.Foreground = fg;
        LabelElement.Text = Text ?? "";
        IconElement.Foreground = fg;

        var glyph = Glyph ?? "";
        if (glyph.Length > 0)
        {
            IconElement.Glyph = glyph;
            IconElement.Visibility = Visibility.Visible;
        }
        else
        {
            IconElement.Visibility = Visibility.Collapsed;
        }
    }

    private static Color ToneColor(BadgeTone tone) => tone switch
    {
        BadgeTone.Accent => Autumn.Colors.Clay,
        BadgeTone.Success => Autumn.Colors.Success,
        BadgeTone.Warning => Autumn.Colors.Warning,
        BadgeTone.Danger => Autumn.Colors.Danger,
        BadgeTone.Info => Autumn.Colors.Slate,
        BadgeTone.Memory => Autumn.Colors.Memory,
        BadgeTone.Sage => Autumn.Colors.Sage,
        // Neutral leans on the slate companion at low chroma so it still reads as paper.
        _ => Color.FromArgb(0xFF, 0x6E, 0x7B, 0x8B),
    };
}

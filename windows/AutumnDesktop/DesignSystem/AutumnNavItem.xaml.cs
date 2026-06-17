using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.DesignSystem;

/// <summary>
/// A hand-drawn sidebar navigation row — the bespoke replacement for
/// NavigationViewItem. Selection, hover, and normal looks are applied from code
/// (theme-aware via <see cref="FrameworkElement.ActualTheme"/>) so nothing reads
/// as stock Fluent. Mutual exclusion is managed by the parent (MainWindow):
/// it sets <see cref="IsSelected"/> and listens to <see cref="Selected"/>.
/// </summary>
public sealed partial class AutumnNavItem : UserControl
{
    private bool _hovered;

    /// <summary>Raised when the row is tapped; the parent routes by <see cref="FrameworkElement.Tag"/>.</summary>
    public event EventHandler? Selected;

    public AutumnNavItem()
    {
        InitializeComponent();
        Root.PointerEntered += (_, _) => { _hovered = true; Apply(); };
        Root.PointerExited += (_, _) => { _hovered = false; Apply(); };
        Tapped += (_, _) => Selected?.Invoke(this, EventArgs.Empty);
        ActualThemeChanged += (_, _) => Apply();
        Loaded += (_, _) => Apply();
    }

    public static readonly DependencyProperty GlyphProperty =
        DependencyProperty.Register(nameof(Glyph), typeof(string), typeof(AutumnNavItem),
            new PropertyMetadata("", OnChanged));

    /// <summary>A Segoe Fluent Icons glyph for the leading icon.</summary>
    public string Glyph
    {
        get => (string)GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public static readonly DependencyProperty LabelProperty =
        DependencyProperty.Register(nameof(Label), typeof(string), typeof(AutumnNavItem),
            new PropertyMetadata("", OnChanged));

    public string Label
    {
        get => (string)GetValue(LabelProperty);
        set => SetValue(LabelProperty, value);
    }

    public static readonly DependencyProperty IsSelectedProperty =
        DependencyProperty.Register(nameof(IsSelected), typeof(bool), typeof(AutumnNavItem),
            new PropertyMetadata(false, OnChanged));

    public bool IsSelected
    {
        get => (bool)GetValue(IsSelectedProperty);
        set => SetValue(IsSelectedProperty, value);
    }

    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((AutumnNavItem)d).Apply();

    private void Apply()
    {
        IconElement.Glyph = Glyph ?? "";
        LabelElement.Text = Label ?? "";

        var dark = ActualTheme == ElementTheme.Dark;
        var clay = Autumn.Colors.Clay;

        if (IsSelected)
        {
            // Clay-tinted surface + clay glyph/label, the way the brand owns the row.
            Root.Background = new SolidColorBrush(Color.FromArgb(0x26, clay.R, clay.G, clay.B));
            var fg = new SolidColorBrush(dark ? Autumn.Colors.ClayLight : clay);
            IconElement.Foreground = fg;
            LabelElement.Foreground = fg;
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
        }
        else if (_hovered)
        {
            // Subtle neutral wash on hover.
            Root.Background = new SolidColorBrush(dark
                ? Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0x0C, 0x00, 0x00, 0x00));
            var fg = new SolidColorBrush(dark
                ? Color.FromArgb(0xF0, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0xE4, 0x1A, 0x1A, 0x1A));
            IconElement.Foreground = fg;
            LabelElement.Foreground = fg;
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.Normal;
        }
        else
        {
            Root.Background = new SolidColorBrush(Colors.Transparent);
            var fg = new SolidColorBrush(dark
                ? Color.FromArgb(0xB8, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0xB0, 0x1A, 0x1A, 0x1A));
            IconElement.Foreground = fg;
            LabelElement.Foreground = fg;
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.Normal;
        }
    }
}

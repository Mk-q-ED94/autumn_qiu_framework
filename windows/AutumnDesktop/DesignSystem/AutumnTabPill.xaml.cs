using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop.DesignSystem;

/// <summary>
/// Horizontal pill-shaped tab button — the tab-bar sibling of <see cref="AutumnNavItem"/>.
/// Used in Settings (server/models/memory/integrations/advanced) and Memory
/// (Mom1/Mom2/Mom3/shared) to replace the stock <c>SelectorBar</c>. Mutual
/// exclusion is managed by the parent page, which holds the active-tab reference.
/// </summary>
public sealed partial class AutumnTabPill : UserControl
{
    private bool _hovered;

    /// <summary>Raised when the pill is tapped; the parent routes by Tag or reference.</summary>
    public event EventHandler? Selected;

    public AutumnTabPill()
    {
        InitializeComponent();
        Root.PointerEntered += (_, _) => { _hovered = true; Apply(); };
        Root.PointerExited += (_, _) => { _hovered = false; Apply(); };
        Tapped += (_, _) => Selected?.Invoke(this, EventArgs.Empty);
        ActualThemeChanged += (_, _) => Apply();
        Loaded += (_, _) => Apply();
    }

    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(nameof(Text), typeof(string), typeof(AutumnTabPill),
            new PropertyMetadata("", OnChanged));

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public static readonly DependencyProperty IsSelectedProperty =
        DependencyProperty.Register(nameof(IsSelected), typeof(bool), typeof(AutumnTabPill),
            new PropertyMetadata(false, OnChanged));

    public bool IsSelected
    {
        get => (bool)GetValue(IsSelectedProperty);
        set => SetValue(IsSelectedProperty, value);
    }

    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
        => ((AutumnTabPill)d).Apply();

    private void Apply()
    {
        LabelElement.Text = Text ?? "";
        var dark = ActualTheme == ElementTheme.Dark;
        var clay = Autumn.Colors.Clay;

        if (IsSelected)
        {
            Root.Background = new SolidColorBrush(Color.FromArgb(0x26, clay.R, clay.G, clay.B));
            LabelElement.Foreground = new SolidColorBrush(dark ? Autumn.Colors.ClayLight : clay);
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
        }
        else if (_hovered)
        {
            Root.Background = new SolidColorBrush(dark
                ? Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0x0C, 0x00, 0x00, 0x00));
            LabelElement.Foreground = new SolidColorBrush(dark
                ? Color.FromArgb(0xE0, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0xD8, 0x1A, 0x1A, 0x1A));
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.Normal;
        }
        else
        {
            Root.Background = new SolidColorBrush(Colors.Transparent);
            LabelElement.Foreground = new SolidColorBrush(dark
                ? Color.FromArgb(0x90, 0xFF, 0xFF, 0xFF)
                : Color.FromArgb(0x80, 0x1A, 0x1A, 0x1A));
            LabelElement.FontWeight = Microsoft.UI.Text.FontWeights.Normal;
        }
    }
}

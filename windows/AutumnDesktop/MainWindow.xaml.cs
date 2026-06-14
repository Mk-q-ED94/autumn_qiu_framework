using System;
using AutumnDesktop.Chat;
using AutumnDesktop.DesignSystem;
using AutumnDesktop.Memory;
using AutumnDesktop.Settings;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace AutumnDesktop;

public sealed partial class MainWindow : Window
{
    private AutumnNavItem? _activeItem;

    public MainWindow()
    {
        InitializeComponent();

        // ── Custom title bar ─────────────────────────────────────────────
        // Extend our XAML into the title-bar area so the brand mark fills it.
        // SetTitleBar marks TitleBar as the drag region; the system draws its
        // caption buttons (close / min / max) at the top-right automatically.
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(TitleBar);

        // Make caption buttons transparent so they float on AutumnSidebarBrush.
        // Clay-tinted hover/pressed so the buttons feel on-brand.
        if (AppWindow?.TitleBar is { } tb)
        {
            tb.ButtonBackgroundColor         = Colors.Transparent;
            tb.ButtonInactiveBackgroundColor = Colors.Transparent;
            tb.ButtonHoverBackgroundColor    = Color.FromArgb(0x28, 0xCC, 0x66, 0x45);
            tb.ButtonPressedBackgroundColor  = Color.FromArgb(0x44, 0xCC, 0x66, 0x45);
        }

        // ── Mica backdrop ────────────────────────────────────────────────
        // Mica shows through the transparent content area; the sidebar uses its
        // own AutumnSidebarBrush so the two regions read as distinct surfaces.
        if (Microsoft.UI.Composition.SystemBackdrops.MicaController.IsSupported())
            SystemBackdrop = new MicaBackdrop();

        // ── Initial navigation ────────────────────────────────────────────
        _activeItem = NavChat;
        ContentFrame.Navigate(typeof(ChatPage));

        _ = App.ServerManager.StartIfNeededAsync(App.Settings.ServerUrl);
    }

    /// <summary>
    /// Handles taps on any AutumnNavItem — deselects the previous item,
    /// selects the new one, and navigates the content frame.
    /// </summary>
    private void NavItem_Selected(object? sender, EventArgs e)
    {
        if (sender is not AutumnNavItem next) return;
        if (ReferenceEquals(_activeItem, next)) return;

        if (_activeItem is not null) _activeItem.IsSelected = false;
        _activeItem = next;
        next.IsSelected = true;

        switch (next.Tag as string)
        {
            case "Chat":     ContentFrame.Navigate(typeof(ChatPage));     break;
            case "Memory":   ContentFrame.Navigate(typeof(MemoryPage));   break;
            case "Settings": ContentFrame.Navigate(typeof(SettingsPage)); break;
        }
    }
}

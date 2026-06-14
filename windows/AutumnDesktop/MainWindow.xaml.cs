using AutumnDesktop.Chat;
using AutumnDesktop.Memory;
using AutumnDesktop.Settings;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace AutumnDesktop;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        // Mica backdrop — the Windows analogue of the macOS app's translucent
        // material canvas, so the Paper & Clay warmth wash reads as warm paper.
        if (Microsoft.UI.Composition.SystemBackdrops.MicaController.IsSupported())
            SystemBackdrop = new MicaBackdrop();
        // Start on the chat page and kick the local-server check in the background.
        Nav.SelectedItem = Nav.MenuItems[0];
        ContentFrame.Navigate(typeof(ChatPage));
        _ = App.ServerManager.StartIfNeededAsync(App.Settings.ServerUrl);
    }

    private void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItem is not NavigationViewItem item) return;
        switch (item.Tag as string)
        {
            case "Chat": ContentFrame.Navigate(typeof(ChatPage)); break;
            case "Memory": ContentFrame.Navigate(typeof(MemoryPage)); break;
            case "Settings": ContentFrame.Navigate(typeof(SettingsPage)); break;
        }
    }
}

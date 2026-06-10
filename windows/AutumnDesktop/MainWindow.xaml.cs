using AutumnDesktop.Chat;
using AutumnDesktop.Memory;
using AutumnDesktop.Settings;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
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

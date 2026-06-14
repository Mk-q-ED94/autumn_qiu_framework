using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Settings;

public sealed partial class SettingsPage : Page
{
    public SettingsViewModel ViewModel { get; } = new();

    public SettingsPage()
    {
        InitializeComponent();
        // PasswordBox.Password isn't a dependency property, so seed from settings
        // on load and push edits back via PasswordChanged.
        Loaded += (_, _) =>
        {
            A1Key.Password = ViewModel.Settings.A1.ApiKey;
            A2Key.Password = ViewModel.Settings.A2.ApiKey;
            A3Key.Password = ViewModel.Settings.A3.ApiKey;
            A4Key.Password = ViewModel.Settings.A4.ApiKey;
            // Start on the Server tab.
            SettingsTabBar.SelectedItem = TabServer;
        };
    }

    private void SettingsTabBar_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        var selected = sender.SelectedItem;
        ServerTabContent.Visibility = selected == TabServer ? Visibility.Visible : Visibility.Collapsed;
        ModelsTabContent.Visibility = selected == TabModels ? Visibility.Visible : Visibility.Collapsed;
        MemoryTabContent.Visibility = selected == TabMemory ? Visibility.Visible : Visibility.Collapsed;
        IntegrationsTabContent.Visibility = selected == TabIntegrations ? Visibility.Visible : Visibility.Collapsed;
        AdvancedTabContent.Visibility = selected == TabAdvanced ? Visibility.Visible : Visibility.Collapsed;
    }

    private void A1Key_PasswordChanged(object sender, RoutedEventArgs e)
        => ViewModel.Settings.A1.ApiKey = A1Key.Password;

    private void A2Key_PasswordChanged(object sender, RoutedEventArgs e)
        => ViewModel.Settings.A2.ApiKey = A2Key.Password;

    private void A3Key_PasswordChanged(object sender, RoutedEventArgs e)
        => ViewModel.Settings.A3.ApiKey = A3Key.Password;

    private void A4Key_PasswordChanged(object sender, RoutedEventArgs e)
        => ViewModel.Settings.A4.ApiKey = A4Key.Password;
}

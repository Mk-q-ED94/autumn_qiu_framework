using System;
using AutumnDesktop.DesignSystem;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Settings;

public sealed partial class SettingsPage : Page
{
    public SettingsViewModel ViewModel { get; } = new();

    private AutumnTabPill? _activeTab;

    public SettingsPage()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            A1Key.Password = ViewModel.Settings.A1.ApiKey;
            A2Key.Password = ViewModel.Settings.A2.ApiKey;
            A3Key.Password = ViewModel.Settings.A3.ApiKey;
            A4Key.Password = ViewModel.Settings.A4.ApiKey;
            _activeTab = TabServer;
        };
    }

    private void Tab_Selected(object? sender, EventArgs e)
    {
        if (sender is not AutumnTabPill next) return;
        if (ReferenceEquals(_activeTab, next)) return;

        if (_activeTab is not null) _activeTab.IsSelected = false;
        _activeTab = next;
        next.IsSelected = true;

        ServerTabContent.Visibility       = ReferenceEquals(next, TabServer)       ? Visibility.Visible : Visibility.Collapsed;
        ModelsTabContent.Visibility       = ReferenceEquals(next, TabModels)       ? Visibility.Visible : Visibility.Collapsed;
        MemoryTabContent.Visibility       = ReferenceEquals(next, TabMemory)       ? Visibility.Visible : Visibility.Collapsed;
        IntegrationsTabContent.Visibility = ReferenceEquals(next, TabIntegrations) ? Visibility.Visible : Visibility.Collapsed;
        AdvancedTabContent.Visibility     = ReferenceEquals(next, TabAdvanced)     ? Visibility.Visible : Visibility.Collapsed;
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

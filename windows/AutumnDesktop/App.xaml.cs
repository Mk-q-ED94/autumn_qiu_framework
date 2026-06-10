using AutumnDesktop.Services;
using AutumnDesktop.Settings;
using Microsoft.UI.Xaml;

namespace AutumnDesktop;

public partial class App : Application
{
    /// <summary>Process-wide singletons shared across pages (simple service locator).</summary>
    public static AppSettings Settings { get; } = AppSettings.Load();
    public static LocalServerManager ServerManager { get; } = new();

    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        _window.Closed += (_, _) =>
        {
            // Tear down the managed Python server with the app.
            ServerManager.Stop();
            Settings.Save();
        };
        _window.Activate();
    }
}

using AutumnDesktop.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Memory;

public sealed partial class MemoryPage : Page
{
    public MemoryViewModel ViewModel { get; } = new();

    public MemoryPage()
    {
        InitializeComponent();
        AreaSegmented.SelectedIndex = 0;
        Loaded += (_, _) => _ = ViewModel.LoadAsync();
    }

    private void AreaSegmented_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        ViewModel.SelectedArea = AreaSegmented.SelectedIndex switch
        {
            1 => MemoryArea.Mom2,
            2 => MemoryArea.Mom3,
            3 => MemoryArea.Shared,
            _ => MemoryArea.Mom1,
        };
    }
}

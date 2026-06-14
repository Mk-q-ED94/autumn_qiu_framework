using AutumnDesktop.Models;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Memory;

public sealed partial class MemoryPage : Page
{
    public MemoryViewModel ViewModel { get; } = new();

    public MemoryPage()
    {
        InitializeComponent();
        AreaSelector.SelectedItem = AreaSelector.Items[0];
        Loaded += (_, _) => _ = ViewModel.LoadAsync();
    }

    private void AreaSelector_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        var index = sender.SelectedItem is null ? 0 : sender.Items.IndexOf(sender.SelectedItem);
        ViewModel.SelectedArea = index switch
        {
            1 => MemoryArea.Mom2,
            2 => MemoryArea.Mom3,
            3 => MemoryArea.Shared,
            _ => MemoryArea.Mom1,
        };
    }
}

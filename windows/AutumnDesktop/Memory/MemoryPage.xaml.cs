using System;
using AutumnDesktop.DesignSystem;
using AutumnDesktop.Models;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Memory;

public sealed partial class MemoryPage : Page
{
    public MemoryViewModel ViewModel { get; } = new();

    private AutumnTabPill? _activeArea;

    public MemoryPage()
    {
        InitializeComponent();
        _activeArea = TabMom1;
        Loaded += (_, _) => _ = ViewModel.LoadAsync();
    }

    private void AreaTab_Selected(object? sender, EventArgs e)
    {
        if (sender is not AutumnTabPill next) return;
        if (ReferenceEquals(_activeArea, next)) return;

        if (_activeArea is not null) _activeArea.IsSelected = false;
        _activeArea = next;
        next.IsSelected = true;

        ViewModel.SelectedArea = next.Tag as string switch
        {
            "Mom2"   => MemoryArea.Mom2,
            "Mom3"   => MemoryArea.Mom3,
            "Shared" => MemoryArea.Shared,
            _        => MemoryArea.Mom1,
        };
    }
}

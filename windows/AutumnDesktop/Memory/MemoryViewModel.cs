using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using AutumnDesktop.Models;
using AutumnDesktop.Networking;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace AutumnDesktop.Memory;

/// <summary>Browses Mom1/2/3 + shared memory history (mirrors macOS MemoryViewModel).</summary>
public sealed partial class MemoryViewModel : ObservableObject
{
    public ObservableCollection<MemoryEntry> Entries { get; } = new();

    public IReadOnlyList<MemoryArea> Areas { get; } =
        new[] { MemoryArea.Mom1, MemoryArea.Mom2, MemoryArea.Mom3, MemoryArea.Shared };

    [ObservableProperty] private MemoryArea _selectedArea = MemoryArea.Mom1;
    [ObservableProperty] private bool _isLoading;
    [ObservableProperty] private string? _errorMessage;
    /// <summary>Drives the empty-state placeholder when an area has no history.</summary>
    [ObservableProperty] private bool _hasEntries;

    partial void OnSelectedAreaChanged(MemoryArea value) => _ = LoadAsync();

    private static AutumnClient BuildClient()
    {
        if (!Uri.TryCreate(App.Settings.ServerUrl, UriKind.Absolute, out var baseUrl))
            throw new AutumnClientException("服务器 URL 无效");
        return new AutumnClient(baseUrl);
    }

    [RelayCommand]
    public async Task LoadAsync()
    {
        IsLoading = true;
        ErrorMessage = null;
        try
        {
            var entries = await BuildClient().MemoryHistoryAsync(SelectedArea);
            Entries.Clear();
            foreach (var e in entries) Entries.Add(e);
            HasEntries = Entries.Count > 0;
        }
        catch (Exception ex)
        {
            ErrorMessage = ex.Message;
        }
        finally
        {
            IsLoading = false;
        }
    }
}

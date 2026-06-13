using AutumnDesktop.Models;
using CommunityToolkit.Mvvm.ComponentModel;

namespace AutumnDesktop.Chat;

public enum ChatRole { User, Assistant }

/// <summary>A single chat bubble; assistant messages may carry a workflow trace.</summary>
public sealed partial class ChatMessage : ObservableObject
{
    [ObservableProperty] private string _text = "";
    [ObservableProperty] private WorkflowTrace? _trace;

    public ChatRole Role { get; init; }

    public bool IsUser => Role == ChatRole.User;
    public bool IsAssistant => Role == ChatRole.Assistant;

    // Bindable alignment/visibility helpers for the bubble template.
    public Microsoft.UI.Xaml.HorizontalAlignment Alignment =>
        IsUser ? Microsoft.UI.Xaml.HorizontalAlignment.Right : Microsoft.UI.Xaml.HorizontalAlignment.Left;

    public Microsoft.UI.Xaml.Visibility TraceVisibility =>
        Trace is not null ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    partial void OnTraceChanged(WorkflowTrace? value) => OnPropertyChanged(nameof(TraceVisibility));
}

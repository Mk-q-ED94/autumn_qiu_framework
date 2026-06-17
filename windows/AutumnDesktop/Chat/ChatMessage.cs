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

    /// <summary>Show text once the assistant has at least one character.</summary>
    public Microsoft.UI.Xaml.Visibility TextVisibility =>
        Text.Length > 0 ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    /// <summary>Show the typing dots while the assistant reply is still empty.</summary>
    public Microsoft.UI.Xaml.Visibility TypingVisibility =>
        Text.Length == 0 ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    public Microsoft.UI.Xaml.Visibility TraceVisibility =>
        Trace is not null ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    partial void OnTextChanged(string value)
    {
        OnPropertyChanged(nameof(TextVisibility));
        OnPropertyChanged(nameof(TypingVisibility));
    }

    partial void OnTraceChanged(WorkflowTrace? value) => OnPropertyChanged(nameof(TraceVisibility));
}

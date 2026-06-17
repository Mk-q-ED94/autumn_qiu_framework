using System.Collections.Specialized;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Windows.System;

namespace AutumnDesktop.Chat;

public sealed partial class ChatPage : Page
{
    public ChatViewModel ViewModel { get; } = new();

    public ChatPage()
    {
        InitializeComponent();
        // Auto-scroll to the bottom when new messages or new tokens arrive so the
        // user always sees the latest content without manual scrolling.
        ViewModel.Messages.CollectionChanged += OnMessagesChanged;
        ViewModel.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(ChatViewModel.IsBusy) && ViewModel.IsBusy)
                ScrollToBottom();
        };
    }

    private void OnMessagesChanged(object? sender, NotifyCollectionChangedEventArgs e)
        => ScrollToBottom();

    private void ScrollToBottom()
        => DispatcherQueue.TryEnqueue(() =>
            MessageScroller.ScrollToVerticalOffset(MessageScroller.ExtentHeight));

    /// <summary>Enter sends; Shift+Enter inserts a newline.</summary>
    private void InputBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Enter) return;

        var shift = Microsoft.UI.Input.InputKeyboardSource
            .GetKeyStateForCurrentThread(VirtualKey.Shift)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        if (shift) return;

        e.Handled = true;
        if (ViewModel.SendCommand.CanExecute(null))
            ViewModel.SendCommand.Execute(null);
    }
}

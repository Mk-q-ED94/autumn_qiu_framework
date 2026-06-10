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
    }

    /// <summary>Enter sends; Shift+Enter inserts a newline.</summary>
    private void InputBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key != VirtualKey.Enter) return;

        var shift = Microsoft.UI.Input.InputKeyboardSource
            .GetKeyStateForCurrentThread(VirtualKey.Shift)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        if (shift) return; // allow newline

        e.Handled = true;
        if (ViewModel.SendCommand.CanExecute(null))
            ViewModel.SendCommand.Execute(null);
    }
}

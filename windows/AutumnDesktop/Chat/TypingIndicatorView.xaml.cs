using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Chat;

/// <summary>
/// Sequential three-dot animation shown while the assistant is typing. The
/// bright dot cycles left→right at 320 ms per step, matching the macOS
/// TypingIndicator view. Timer is started/stopped with the control lifetime so
/// it doesn't tick in a collapsed Visibility state.
/// </summary>
public sealed partial class TypingIndicatorView : UserControl
{
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMilliseconds(320) };
    private int _phase;

    public TypingIndicatorView()
    {
        InitializeComponent();
        Loaded += (_, _) => _timer.Start();
        Unloaded += (_, _) => _timer.Stop();
        _timer.Tick += (_, _) =>
        {
            _phase = (_phase + 1) % 3;
            Dot0.Opacity = _phase == 0 ? 1.0 : 0.3;
            Dot1.Opacity = _phase == 1 ? 1.0 : 0.3;
            Dot2.Opacity = _phase == 2 ? 1.0 : 0.3;
        };
    }
}

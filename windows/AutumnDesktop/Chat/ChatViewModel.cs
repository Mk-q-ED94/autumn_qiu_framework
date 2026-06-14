using System;
using System.Collections.ObjectModel;
using System.Threading;
using System.Threading.Tasks;
using AutumnDesktop.Models;
using AutumnDesktop.Networking;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.UI.Dispatching;

namespace AutumnDesktop.Chat;

/// <summary>
/// Drives the collaboration view: sends input to the server, streams the reply
/// token-by-token, and attaches the final WP1/WP2/WP3 workflow trace. Mirrors
/// the macOS ChatViewModel.
/// </summary>
public sealed partial class ChatViewModel : ObservableObject
{
    private readonly DispatcherQueue _dispatcher = DispatcherQueue.GetForCurrentThread();
    private CancellationTokenSource? _activeSend;

    public ObservableCollection<ChatMessage> Messages { get; } = new();

    [ObservableProperty] private string _input = "";
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private string? _errorMessage;
    /// <summary>Drives the empty-state placeholder (shown while no turns exist).</summary>
    [ObservableProperty] private bool _hasMessages;
    /// <summary>Short label shown in the streaming status bar ("A1 → A2" etc.).</summary>
    [ObservableProperty] private string _runStatusText = "";

    private AutumnClient BuildClient()
    {
        var url = App.Settings.ServerUrl;
        if (!Uri.TryCreate(url, UriKind.Absolute, out var baseUrl))
            throw new AutumnClientException("服务器 URL 无效");
        return new AutumnClient(baseUrl);
    }

    public bool CanSend => !IsBusy && !string.IsNullOrWhiteSpace(Input);

    partial void OnInputChanged(string value) => SendCommand.NotifyCanExecuteChanged();
    partial void OnIsBusyChanged(bool value) => SendCommand.NotifyCanExecuteChanged();

    [RelayCommand(CanExecute = nameof(CanSend))]
    private async Task SendAsync()
    {
        var text = Input.Trim();
        if (text.Length == 0) return;

        ErrorMessage = null;
        Input = "";
        Messages.Add(new ChatMessage { Role = ChatRole.User, Text = text });

        var assistant = new ChatMessage { Role = ChatRole.Assistant, Text = "" };
        Messages.Add(assistant);
        HasMessages = true;

        IsBusy = true;
        RunStatusText = "";
        _activeSend = new CancellationTokenSource();
        var route = App.Settings.MissionRoute;
        if (route == "auto") route = null;

        try
        {
            var client = BuildClient();
            var request = new ProcessRequest(text, Route: route);
            await foreach (var evt in client.StreamAsync(request, _activeSend.Token))
            {
                switch (evt)
                {
                    case StreamEvent.Chunk chunk:
                        _dispatcher.TryEnqueue(() => assistant.Text += chunk.Text);
                        break;
                    case StreamEvent.Trace trace:
                        _dispatcher.TryEnqueue(() =>
                        {
                            assistant.Trace = trace.Value;
                            var t = trace.Value;
                            RunStatusText = t.InputType.Length > 0
                                ? $"· {t.InputType}"
                                : "";
                        });
                        break;
                }
            }

            // Some servers (validate_before_stream) emit only the final text; if
            // no chunks arrived but the trace carries output, surface that.
            if (string.IsNullOrEmpty(assistant.Text) && assistant.Trace is { Output.Length: > 0 } t)
                assistant.Text = t.Output;
        }
        catch (OperationCanceledException)
        {
            if (string.IsNullOrEmpty(assistant.Text))
                assistant.Text = "（已取消）";
        }
        catch (Exception ex)
        {
            ErrorMessage = ex.Message;
            if (string.IsNullOrEmpty(assistant.Text))
                Messages.Remove(assistant);
        }
        finally
        {
            IsBusy = false;
            RunStatusText = "";
            _activeSend?.Dispose();
            _activeSend = null;
        }
    }

    [RelayCommand]
    private void Cancel() => _activeSend?.Cancel();

    [RelayCommand]
    private async Task EndSessionAsync()
    {
        try
        {
            await BuildClient().EndSessionAsync();
            Messages.Clear();
            HasMessages = false;
        }
        catch (Exception ex)
        {
            ErrorMessage = ex.Message;
        }
    }
}

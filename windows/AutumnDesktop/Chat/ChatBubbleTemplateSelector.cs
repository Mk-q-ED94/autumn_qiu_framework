using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AutumnDesktop.Chat;

/// <summary>
/// Picks the user vs assistant bubble template so each side gets its own
/// alignment and surface — clay-tinted user turns, neutral assistant turns with
/// the collapsible workflow trace. The WinUI parallel of the macOS ChatView's
/// branching on message role.
/// </summary>
public sealed partial class ChatBubbleTemplateSelector : DataTemplateSelector
{
    public DataTemplate? UserTemplate { get; set; }
    public DataTemplate? AssistantTemplate { get; set; }

    protected override DataTemplate? SelectTemplateCore(object item)
        => item is ChatMessage { IsUser: true } ? UserTemplate : AssistantTemplate;

    protected override DataTemplate? SelectTemplateCore(object item, DependencyObject container)
        => SelectTemplateCore(item);
}

using System;
using AutumnDesktop.DesignSystem;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Media;

namespace AutumnDesktop.Common;

/// <summary>True when the bound value is non-null (and, for strings, non-empty).</summary>
public sealed class NotNullToBoolConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
        => value switch
        {
            null => false,
            string s => s.Length > 0,
            _ => true,
        };

    public object ConvertBack(object value, Type targetType, object parameter, string language)
        => throw new NotSupportedException();
}

/// <summary>Maps a non-empty/non-null value to Visible, else Collapsed.</summary>
public sealed class NotNullToVisibilityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var visible = value switch
        {
            null => false,
            string s => s.Length > 0,
            _ => true,
        };
        return visible ? Visibility.Visible : Visibility.Collapsed;
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language)
        => throw new NotSupportedException();
}

/// <summary>
/// bool → Visibility. Pass ConverterParameter="Invert" to flip (true → Collapsed),
/// which drives empty-state placeholders that show when a flag is false.
/// </summary>
public sealed class BoolToVisibilityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var flag = value is bool b && b;
        if (parameter is string s && s.Equals("Invert", StringComparison.OrdinalIgnoreCase))
            flag = !flag;
        return flag ? Visibility.Visible : Visibility.Collapsed;
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language)
        => throw new NotSupportedException();
}

/// <summary>
/// A workspace tag ("wp1"/"wp2"/"wp3"/"wp4"/"shared") → its identity brush, so a
/// trace stage's accent bar carries the same colour as the macOS pipeline strip.
/// </summary>
public sealed class WorkspaceToBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
        => new SolidColorBrush(Autumn.Colors.Workspace(value as string ?? ""));

    public object ConvertBack(object value, Type targetType, object parameter, string language)
        => throw new NotSupportedException();
}

/// <summary>
/// A stage status ("completed"/"active"/"failed"/"pending") → a status brush.
/// Completed/active stay on the workspace tint via opacity in XAML; failed → red,
/// pending → muted. Used for the small stage status dot.
/// </summary>
public sealed class StatusToBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var color = (value as string ?? "").ToLowerInvariant() switch
        {
            "failed" => Autumn.Colors.Danger,
            "completed" => Autumn.Colors.Success,
            "active" => Autumn.Colors.Warning,
            _ => Autumn.Colors.Info,
        };
        return new SolidColorBrush(color);
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language)
        => throw new NotSupportedException();
}

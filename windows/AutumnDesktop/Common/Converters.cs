using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;

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

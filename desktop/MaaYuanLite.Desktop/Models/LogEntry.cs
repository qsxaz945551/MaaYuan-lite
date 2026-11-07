using System.Windows.Media;

namespace MaaYuanLite.Desktop.Models;

/// <summary>One rendered log line. Colour is decided once, at creation.</summary>
public sealed class LogEntry
{
    private static readonly SolidColorBrush Error = Frozen(0xDF, 0x7F, 0x7F);
    private static readonly SolidColorBrush Warn = Frozen(0xD8, 0xA8, 0x5F);
    private static readonly SolidColorBrush Normal = Frozen(0xC6, 0xD0, 0xDC);

    public string Time { get; init; } = "";
    public string Level { get; init; } = "";
    public string Message { get; init; } = "";

    public string LevelText => Level.ToUpperInvariant();

    public Brush Brush => Level switch
    {
        "error" => Error,
        "warn" => Warn,
        _ => Normal,
    };

    private static SolidColorBrush Frozen(byte r, byte g, byte b)
    {
        var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
        brush.Freeze();
        return brush;
    }
}

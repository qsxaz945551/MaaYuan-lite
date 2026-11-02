using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using MaaYuanLite.Desktop.Services;

namespace MaaYuanLite.Desktop;

public partial class MainWindow : Window
{
    private readonly LiteService _service = new();
    private readonly ObservableCollection<string> _logs = new();
    private readonly ObservableCollection<string> _tasks = new();
    private DispatcherTimer? _timer;
    private int _cursor;

    public MainWindow()
    {
        InitializeComponent();
        LogList.ItemsSource = _logs;
        TaskList.ItemsSource = _tasks;
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "正在启动服务……";
        var started = await _service.StartAsync();
        if (!started)
        {
            StatusText.Text = _service.LastError ?? "服务启动失败";
            return;
        }

        FootText.Text = $"{_service.BaseUri}    root: {_service.Root}";
        await RefreshAsync();

        // Headless UI check: renders the window to PNG and exits. Used by the
        // build script and by manual smoke tests on machines without a visible
        // desktop session.
        var args = Environment.GetCommandLineArgs();
        var shotIndex = Array.IndexOf(args, "--screenshot");
        if (shotIndex >= 0 && shotIndex + 1 < args.Length)
        {
            await Task.Delay(1500);
            SaveScreenshot(args[shotIndex + 1]);
            Application.Current.Shutdown();
            return;
        }

        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        _timer.Tick += async (_, _) => await RefreshAsync();
        _timer.Start();
    }

    private void SaveScreenshot(string path)
    {
        UpdateLayout();
        var width = (int)Math.Max(ActualWidth, 1);
        var height = (int)Math.Max(ActualHeight, 1);
        var bitmap = new RenderTargetBitmap(width, height, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(this);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = File.Create(path);
        encoder.Save(stream);
    }

    private async Task RefreshAsync()
    {
        using var doc = await _service.GetAsync($"/api/state?since={_cursor}");
        if (doc is null)
        {
            return;
        }

        var root = doc.RootElement;
        var status = root.GetProperty("status").GetString() ?? "";
        var current = root.GetProperty("currentTask").GetString() ?? "";
        StatusText.Text = string.IsNullOrEmpty(current) ? status : $"{status} · {current}";

        var tasks = root.GetProperty("tasks").EnumerateArray().ToList();
        if (tasks.Count != _tasks.Count)
        {
            _tasks.Clear();
            foreach (var task in tasks)
            {
                _tasks.Add(FormatTask(task));
            }
        }
        else
        {
            for (var i = 0; i < tasks.Count; i++)
            {
                var line = FormatTask(tasks[i]);
                if (_tasks[i] != line)
                {
                    _tasks[i] = line;
                }
            }
        }

        foreach (var log in root.GetProperty("logs").EnumerateArray())
        {
            _logs.Add($"{log.GetProperty("time").GetString()}  {log.GetProperty("message").GetString()}");
        }
        while (_logs.Count > 800)
        {
            _logs.RemoveAt(0);
        }
        if (root.TryGetProperty("logSeq", out var seq))
        {
            _cursor = seq.GetInt32();
        }
        if (_logs.Count > 0)
        {
            LogList.ScrollIntoView(_logs[^1]);
        }
    }

    private static string FormatTask(JsonElement task)
    {
        var name = task.GetProperty("name").GetString();
        var status = task.GetProperty("status").GetString();
        var mark = status switch
        {
            "succeeded" => "✓",
            "failed" or "timed_out" => "✕",
            "running" => "▶",
            "skipped" => "–",
            "cancelled" => "■",
            _ => "·",
        };
        return $"{mark}  {name}";
    }

    private async void OnCheck(object sender, RoutedEventArgs e)
    {
        var ok = await _service.PostAsync("/api/check");
        StatusText.Text = ok ? "检查中……" : "检查请求失败";
    }

    private async void OnStart(object sender, RoutedEventArgs e)
    {
        var ok = await _service.PostAsync("/api/start", new { training = "修为", dungeon = false });
        StatusText.Text = ok ? "已开始" : "开始失败（可能已有任务在运行）";
    }

    private async void OnStop(object sender, RoutedEventArgs e)
    {
        await _service.PostAsync("/api/stop");
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        _timer?.Stop();
        _service.Dispose();
    }
}

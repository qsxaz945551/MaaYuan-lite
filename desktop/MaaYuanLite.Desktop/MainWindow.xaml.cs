using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using MaaYuanLite.Desktop.Models;
using MaaYuanLite.Desktop.Services;

namespace MaaYuanLite.Desktop;

public partial class MainWindow : Window
{
    private readonly LiteService _service = new();
    private readonly ObservableCollection<string> _logs = new();
    private readonly ObservableCollection<string> _tasks = new();
    private readonly List<string> _taskNames = new();
    private readonly Dictionary<string, List<OptionGroup>> _options = new();
    private DispatcherTimer? _timer;
    private int _cursor;
    private bool _optionsLoaded;
    private bool _loadingSettings;

    private static readonly (string Value, string Label)[] StartupOptions =
    {
        ("none", "只打开界面"),
        ("minimize_only", "打开并最小化"),
        ("auto_run", "自动运行日常"),
        ("auto_run_minimized", "自动运行并最小化"),
    };

    private static readonly (string Value, string Label)[] ShutdownOptions =
    {
        ("none", "不处理"),
        ("close_maa", "关闭 Lite"),
        ("close_both", "关闭模拟器和 Lite"),
    };

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
        await LoadOptionsAsync();
        await LoadSettingsAsync();

        // Headless UI check: renders the window to PNG and exits.
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

        await WarnIfUnhealthyAsync();
        _ = CheckUpdatesAsync();
    }

    private async Task CheckUpdatesAsync()
    {
        try
        {
            using var doc = await _service.GetAsync("/api/updates");
            if (doc is null || !doc.RootElement.TryGetProperty("resource", out var resource))
            {
                return;
            }
            var available = resource.TryGetProperty("available", out var flag) && flag.GetBoolean();
            if (!available)
            {
                UpdateBadge.Visibility = Visibility.Collapsed;
                return;
            }
            var remote = resource.TryGetProperty("remote", out var sha) ? sha.GetString() : null;
            var date = resource.TryGetProperty("remoteDate", out var day) ? day.GetString() : null;
            UpdateText.Text = $"资源有更新 {date}";
            UpdateBadge.Tag = remote;
            UpdateBadge.Visibility = Visibility.Visible;
        }
        catch (Exception)
        {
            // Update checks are best-effort; never surface them as a startup error.
        }
    }

    private void OnUpdateClick(object sender, System.Windows.Input.MouseButtonEventArgs e)
    {
        var remote = UpdateBadge.Tag as string ?? "";
        MessageBox.Show(
            $"上游资源有新版本（{remote}）。\n\n" +
            "自动下载将在下一版本接入；目前可在开发目录运行：\n" +
            "python devtools/sync_repo.py --update\n\n" +
            "更新后先跑 devtools/check_upstream.py，再重启 Lite。",
            "MaaYuan Lite",
            MessageBoxButton.OK,
            MessageBoxImage.Information);
    }

    /// <summary>
    /// Show a dialog only when the environment is genuinely broken (missing
    /// runtime, resources or OCR model). A closed emulator is a warning, not a
    /// failure, so the normal "start the emulator later" flow stays quiet.
    /// </summary>
    private async Task WarnIfUnhealthyAsync()
    {
        using var doc = await _service.GetAsync("/api/health");
        if (doc is null)
        {
            return;
        }
        if (!doc.RootElement.TryGetProperty("ok", out var ok) || ok.GetBoolean())
        {
            return;
        }

        var problems = doc.RootElement.GetProperty("checks").EnumerateArray()
            .Where(check => check.GetProperty("status").GetString() == "fail")
            .Select(check => $"{check.GetProperty("name").GetString()}：{check.GetProperty("detail").GetString()}")
            .ToList();
        if (problems.Count == 0)
        {
            return;
        }

        MessageBox.Show(
            "环境检查未通过：\n\n" + string.Join("\n", problems),
            "MaaYuan Lite",
            MessageBoxButton.OK,
            MessageBoxImage.Warning);
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
        var selected = TaskList.SelectedIndex;
        if (tasks.Count != _tasks.Count)
        {
            _tasks.Clear();
            _taskNames.Clear();
            foreach (var task in tasks)
            {
                _tasks.Add(FormatTask(task));
                _taskNames.Add(task.GetProperty("name").GetString() ?? "");
            }
            if (selected >= 0 && selected < _tasks.Count)
            {
                TaskList.SelectedIndex = selected;
            }
            else if (_tasks.Count > 0 && TaskList.SelectedIndex < 0)
            {
                TaskList.SelectedIndex = 0;
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

    private async Task LoadSettingsAsync()
    {
        _loadingSettings = true;
        try
        {
            var startup = "none";
            var shutdown = "none";
            using var doc = await _service.GetAsync("/api/settings");
            if (doc is not null)
            {
                var root = doc.RootElement;
                startup = root.TryGetProperty("startup_action", out var s) ? s.GetString() ?? "none" : "none";
                shutdown = root.TryGetProperty("shutdown_action", out var d) ? d.GetString() ?? "none" : "none";
            }

            StartupCombo.ItemsSource = StartupOptions.Select(item => item.Label).ToList();
            ShutdownCombo.ItemsSource = ShutdownOptions.Select(item => item.Label).ToList();
            StartupCombo.SelectedIndex = Math.Max(0, Array.FindIndex(StartupOptions, item => item.Value == startup));
            ShutdownCombo.SelectedIndex = Math.Max(0, Array.FindIndex(ShutdownOptions, item => item.Value == shutdown));
        }
        finally
        {
            _loadingSettings = false;
        }
    }

    private async void OnStartupChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loadingSettings || StartupCombo.SelectedIndex < 0)
        {
            return;
        }
        await _service.PostAsync("/api/settings", new
        {
            startup_action = StartupOptions[StartupCombo.SelectedIndex].Value,
        });
    }

    private async void OnShutdownChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loadingSettings || ShutdownCombo.SelectedIndex < 0)
        {
            return;
        }
        await _service.PostAsync("/api/settings", new
        {
            shutdown_action = ShutdownOptions[ShutdownCombo.SelectedIndex].Value,
        });
    }

    private async Task LoadOptionsAsync()
    {
        using var doc = await _service.GetAsync("/api/task-options?scope=daily");
        if (doc is null)
        {
            return;
        }
        if (!doc.RootElement.TryGetProperty("tasks", out var tasks))
        {
            return;
        }

        _options.Clear();
        foreach (var task in tasks.EnumerateArray())
        {
            var name = task.GetProperty("name").GetString() ?? "";
            var groups = new List<OptionGroup>();
            if (task.TryGetProperty("groups", out var array) && array.ValueKind == JsonValueKind.Array)
            {
                foreach (var group in array.EnumerateArray())
                {
                    groups.Add(ParseGroup(group, name));
                }
            }
            _options[name] = groups;
        }
        _optionsLoaded = true;
        RenderSelectedTask();
    }

    private static OptionGroup ParseGroup(JsonElement element, string taskName)
    {
        var cases = new List<string>();
        if (element.TryGetProperty("cases", out var caseArray) && caseArray.ValueKind == JsonValueKind.Array)
        {
            cases.AddRange(caseArray.EnumerateArray().Select(item => item.GetString() ?? ""));
        }

        var fields = new List<OptionField>();
        if (element.TryGetProperty("fields", out var fieldArray) && fieldArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var field in fieldArray.EnumerateArray())
            {
                fields.Add(new OptionField
                {
                    Name = field.GetProperty("name").GetString() ?? "",
                    Label = field.TryGetProperty("label", out var label) ? label.GetString() ?? "" : "",
                    Value = field.TryGetProperty("value", out var value) ? value.GetString() ?? "" : "",
                });
            }
        }

        return new OptionGroup
        {
            TaskName = taskName,
            Group = element.GetProperty("group").GetString() ?? "",
            Type = element.TryGetProperty("type", out var type) ? type.GetString() ?? "select" : "select",
            Depth = element.TryGetProperty("depth", out var depth) ? depth.GetInt32() : 0,
            Description = element.TryGetProperty("description", out var description) ? description.GetString() ?? "" : "",
            Label = element.TryGetProperty("label", out var groupLabel) ? groupLabel.GetString() ?? "" : "",
            Cases = cases,
            Selected = element.TryGetProperty("selected", out var selected) ? selected.GetInt32() : 0,
            Fields = fields,
        };
    }

    private void OnTaskSelected(object sender, SelectionChangedEventArgs e)
    {
        RenderSelectedTask();
    }

    private void RenderSelectedTask()
    {
        var index = TaskList.SelectedIndex;
        if (index < 0 || index >= _taskNames.Count)
        {
            return;
        }
        var name = _taskNames[index];
        Breadcrumb.Text = $"今日日常 › {name}";
        if (!_optionsLoaded)
        {
            return;
        }
        RenderOptions(_options.TryGetValue(name, out var groups) ? groups : new List<OptionGroup>());
    }

    private void RenderOptions(List<OptionGroup> groups)
    {
        OptionsPanel.Children.Clear();
        if (groups.Count == 0)
        {
            OptionsPanel.Children.Add(new TextBlock
            {
                Text = "该任务没有可调选项",
                Foreground = new SolidColorBrush(Color.FromRgb(0x9C, 0xA3, 0xAF)),
            });
            return;
        }

        foreach (var group in groups)
        {
            var row = new Grid { Margin = new Thickness(group.Depth * 16, 0, 0, 12) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var label = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            label.Children.Add(new TextBlock
            {
                Text = group.Group,
                FontWeight = FontWeights.Medium,
                TextWrapping = TextWrapping.Wrap,
            });
            if (!string.IsNullOrEmpty(group.Description))
            {
                label.Children.Add(new TextBlock
                {
                    Text = group.Description,
                    Foreground = new SolidColorBrush(Color.FromRgb(0x6B, 0x72, 0x80)),
                    FontSize = 11,
                    TextWrapping = TextWrapping.Wrap,
                });
            }
            Grid.SetColumn(label, 0);
            row.Children.Add(label);

            var control = group.Type == "input"
                ? BuildInput(group)
                : group.IsSwitch ? BuildSwitch(group) : BuildSelect(group);
            Grid.SetColumn(control, 1);
            row.Children.Add(control);

            OptionsPanel.Children.Add(row);
        }
    }

    private FrameworkElement BuildSelect(OptionGroup group)
    {
        var combo = new ComboBox
        {
            ItemsSource = group.Cases,
            SelectedIndex = Math.Clamp(group.Selected, 0, Math.Max(group.Cases.Count - 1, 0)),
            MinWidth = 170,
            VerticalAlignment = VerticalAlignment.Center,
        };
        combo.SelectionChanged += async (_, _) =>
        {
            if (combo.SelectedIndex < 0)
            {
                return;
            }
            await SaveIndexAsync(group, combo.SelectedIndex);
        };
        return combo;
    }

    private FrameworkElement BuildSwitch(OptionGroup group)
    {
        var isOn = group.Selected == group.OnIndex;
        var check = new CheckBox
        {
            IsChecked = isOn,
            Content = isOn ? "开" : "关",
            MinWidth = 56,
            VerticalAlignment = VerticalAlignment.Center,
        };
        check.Checked += async (_, _) =>
        {
            check.Content = "开";
            await SaveIndexAsync(group, group.OnIndex);
        };
        check.Unchecked += async (_, _) =>
        {
            check.Content = "关";
            await SaveIndexAsync(group, group.OffIndex);
        };
        return check;
    }

    private FrameworkElement BuildInput(OptionGroup group)
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        var boxes = new List<TextBox>();
        foreach (var field in group.Fields)
        {
            if (group.Fields.Count > 1)
            {
                panel.Children.Add(new TextBlock
                {
                    Text = field.Label,
                    Margin = new Thickness(0, 0, 6, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    FontSize = 12,
                });
            }
            var box = new TextBox
            {
                Text = field.Value,
                Width = 150,
                Margin = new Thickness(0, 0, 8, 0),
                Tag = field.Name,
                VerticalAlignment = VerticalAlignment.Center,
            };
            box.LostFocus += async (_, _) =>
            {
                var values = boxes.ToDictionary(item => (string)item.Tag!, item => item.Text);
                await SaveInputsAsync(group, values);
            };
            boxes.Add(box);
            panel.Children.Add(box);
        }
        return panel;
    }

    private async Task SaveIndexAsync(OptionGroup group, int index)
    {
        var ok = await _service.PostAsync("/api/task-options", new
        {
            task = group.TaskName,
            group = group.Group,
            index,
        });
        if (ok)
        {
            // Nested options appear or disappear after a change; reload quietly.
            await LoadOptionsAsync();
        }
    }

    private async Task SaveInputsAsync(OptionGroup group, Dictionary<string, string> values)
    {
        await _service.PostAsync("/api/task-options", new
        {
            task = group.TaskName,
            group = group.Group,
            inputs = values,
        });
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

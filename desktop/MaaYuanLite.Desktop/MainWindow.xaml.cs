using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using MaaYuanLite.Desktop.Models;
using MaaYuanLite.Desktop.Services;

namespace MaaYuanLite.Desktop;

public partial class MainWindow : Window
{
    private sealed record TaskEntry(string Name, string Kind);

    // 步骤条的两种字体：有 focus 走正文，没有则用等宽体示弱，避免误认成中文进度。
    private static readonly FontFamily _uiFont = new("Microsoft YaHei UI");
    private static readonly FontFamily _monoFont = new("Consolas");

    private static readonly (string Type, string TaskName, string Label)[] Trainings =
    {
        ("修为", "💎 修为历练", "💎 修为"),
        ("铜钱", "💲 铜钱历练", "💲 铜钱"),
        ("经验", "⚔️ 经验历练", "⚔️ 经验"),
    };

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

    // Palette handles, frozen once. Colour-per-log-line would otherwise allocate
    // a brush for every line on every poll.
    private static readonly SolidColorBrush TextBrush = Frozen(0xED, 0xF2, 0xF7);
    private static readonly SolidColorBrush MutedBrush = Frozen(0x8D, 0x9B, 0xAD);
    private static readonly SolidColorBrush FaintBrush = Frozen(0x5F, 0x6C, 0x7E);
    private static readonly SolidColorBrush SubBrush = Frozen(0x66, 0x74, 0x8A);
    private static readonly SolidColorBrush AccentBrush = Frozen(0xD9, 0xB3, 0x6C);
    private static readonly SolidColorBrush BlueBrush = Frozen(0x7F, 0xA7, 0xD9);
    private static readonly SolidColorBrush GreenBrush = Frozen(0x74, 0xB8, 0x8B);
    private static readonly SolidColorBrush RedBrush = Frozen(0xDF, 0x7F, 0x7F);
    private static readonly SolidColorBrush AmberBrush = Frozen(0xD8, 0xA8, 0x5F);
    private static readonly SolidColorBrush RowBrush = FrozenA(0x05, 0xFF, 0xFF, 0xFF);
    private static readonly SolidColorBrush RowHoverBrush = FrozenA(0x09, 0xFF, 0xFF, 0xFF);
    private static readonly SolidColorBrush RowSelectedBrush = FrozenA(0x21, 0xD9, 0xB3, 0x6C);
    private static readonly SolidColorBrush RowSelectedBorder = Frozen(0x7A, 0x64, 0x40);

    private readonly LiteService _service = new();
    private readonly ObservableCollection<LogEntry> _logs = new();
    private readonly Dictionary<string, List<OptionGroup>> _options = new();
    private readonly List<string> _allTaskNames = new();
    private readonly List<string> _pinned = new();
    private readonly HashSet<string> _hidden = new();
    private readonly HashSet<string> _dailyChecked = new();
    private readonly HashSet<string> _libraryChecked = new();
    private HashSet<string> _lastPlanNames = new();
    // 记录计划是按哪个小时算的：跨过 16:00 / 24:00 要重算一次，
    // 否则窗口一直开着就永远看不到每日进膳自动出现。
    private int _planHour = -1;
    private bool _syncingSelectAll;
    private readonly List<TaskEntry> _plan = new();
    private readonly List<TaskEntry> _library = new();
    private readonly List<TaskEntry> _stateTasks = new();
    private readonly Dictionary<string, string> _status = new();
    // 服务端给任务的附注（目前只有地宫入口探测失败时的「本期未开放」）。
    private readonly Dictionary<string, string> _notes = new();
    private readonly Dictionary<string, string> _singleResults = new();

    private DispatcherTimer? _timer;
    private string _training = "修为";
    private bool _dungeon;
    private string _scope = "daily";
    private string _selected = "";
    private string _runStatus = "idle";
    private string _singleName = "";
    private string _singleStatus = "";
    private int _singleIndex;
    private int _singleTotal;
    private bool _busy;
    private bool _canResume;
    private bool _loadingSettings;
    private bool _buildingPanel;
    private bool _downloadRunning;
    // 徽章里到底有什么：点击时按这些标志决定"能做什么"，
    // 不再靠字符串判断，也不会因为只提示框架就去问要不要下载资源。
    private bool _updateStaged;
    private bool _updateHasResource;
    private bool _updateHasFramework;
    private bool _uiReady;
    private int _cursor;
    private string _runId = "";
    private string _signature = "";

    public MainWindow()
    {
        InitializeComponent();
        LogList.ItemsSource = _logs;
        _uiReady = true;
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private static SolidColorBrush Frozen(byte r, byte g, byte b)
    {
        var brush = new SolidColorBrush(Color.FromRgb(r, g, b));
        brush.Freeze();
        return brush;
    }

    private static SolidColorBrush FrozenA(byte a, byte r, byte g, byte b)
    {
        var brush = new SolidColorBrush(Color.FromArgb(a, r, g, b));
        brush.Freeze();
        return brush;
    }

    // ---------------------------------------------------------------- startup

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

        await LoadSettingsAsync();
        await LoadOptionsAsync();
        await LoadPlanAsync();
        await RefreshAsync();
        await LoadMetaAsync();

        // Kick off the update check before the slower health check so the badge
        // has time to appear while the window is still settling.
        _ = CheckUpdatesAsync();

        // Headless UI check: renders the window to PNG and exits. "--scope library"
        // lets the check cover the other tab too.
        var args = Environment.GetCommandLineArgs();
        var scopeIndex = Array.IndexOf(args, "--scope");
        if (scopeIndex >= 0 && scopeIndex + 1 < args.Length && args[scopeIndex + 1] == "library")
        {
            LibraryTab.IsChecked = true;
        }
        var shotIndex = Array.IndexOf(args, "--screenshot");
        if (shotIndex >= 0 && shotIndex + 1 < args.Length)
        {
            await Task.Delay(3000);
            SaveScreenshot(args[shotIndex + 1]);
            Application.Current.Shutdown();
            return;
        }

        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        var tick = 0;
        _timer.Tick += async (_, _) =>
        {
            await RefreshAsync();
            // Poll faster while a run is live so task badges do not lag behind.
            _timer!.Interval = TimeSpan.FromSeconds(_busy ? 1 : 2);
            tick++;
            if (DateTime.Now.Hour != _planHour)
            {
                // 每日进膳 16:00 开、地宫看开关；小时变了就把计划重算一次。
                await LoadPlanAsync();
            }
            if (_downloadRunning || tick % 15 == 0)
            {
                await CheckUpdatesAsync();
            }
        };
        _timer.Start();

        await WarnIfUnhealthyAsync();
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
                startup = Str(root, "startupAction");
                if (string.IsNullOrEmpty(startup))
                {
                    startup = "none";
                }
                shutdown = Str(root, "shutdownAction");
                if (string.IsNullOrEmpty(shutdown))
                {
                    shutdown = "none";
                }
                var training = Str(root, "lastTraining");
                if (Trainings.Any(item => item.Type == training))
                {
                    _training = training;
                }
                _dungeon = Bool(root, "lastDungeon");
            }

            StartupCombo.ItemsSource = StartupOptions.Select(item => item.Label).ToList();
            ShutdownCombo.ItemsSource = ShutdownOptions.Select(item => item.Label).ToList();
            StartupCombo.SelectedIndex = Math.Max(0, Array.FindIndex(StartupOptions, item => item.Value == startup));
            ShutdownCombo.SelectedIndex = Math.Max(0, Array.FindIndex(ShutdownOptions, item => item.Value == shutdown));
            DungeonToggle.IsChecked = _dungeon;
            DungeonHint.Text = _dungeon ? "已开启" : "默认关闭";
        }
        finally
        {
            _loadingSettings = false;
        }
    }

    // ------------------------------------------------------------- plan + opts

    private async Task LoadPlanAsync()
    {
        using var doc = await _service.GetAsync(
            $"/api/plan?training={Uri.EscapeDataString(_training)}&dungeon={(_dungeon ? 1 : 0)}");
        if (doc is null)
        {
            return;
        }
        if (!doc.RootElement.TryGetProperty("tasks", out var tasks) || tasks.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        _plan.Clear();
        foreach (var task in tasks.EnumerateArray())
        {
            _plan.Add(new TaskEntry(Str(task, "name"), Str(task, "kind")));
        }

        var currentNames = _plan.Select(task => task.Name).ToHashSet();

        // 不在计划里的任务（地宫关掉、每日进膳不在开放时段）一律清掉勾选：
        // 界面上看不见的项不该在内存里留着"已勾选"，否则按钮上的数字会比实际
        // 执行的多，重新开放时也像是记住了上一次的选择。
        _dailyChecked.RemoveWhere(name => !currentNames.Contains(name));

        // 新出现的任务默认勾上（第一次进界面、地宫/每日进膳刚开放）；用户主动
        // 取消过的不会被重新勾回来，因为只处理"这次新出现的"。
        foreach (var name in currentNames.Except(_lastPlanNames))
        {
            _dailyChecked.Add(name);
        }
        _lastPlanNames = currentNames;
        _planHour = DateTime.Now.Hour;

        RebuildLibrary();
        if (!_plan.Any(task => task.Name == _selected))
        {
            var preferred = Trainings.FirstOrDefault(item => item.Type == _training).TaskName;
            _selected = _plan.Any(task => task.Name == preferred)
                ? preferred
                : (_plan.FirstOrDefault()?.Name ?? "");
        }
        _signature = "";
        RenderTasks();
        RenderOptions();
        UpdateStartButton();
    }

    /// <summary>
    /// 把版本号写进底栏。用户曾直接双击旧包里的 exe 启动，界面和实际代码对不上，
    /// 有这个就能一眼看出跑的是哪一版。
    /// </summary>
    private async Task LoadMetaAsync()
    {
        using var doc = await _service.GetAsync("/api/meta");
        if (doc is null)
        {
            return;
        }
        var version = Str(doc.RootElement, "version");
        if (!string.IsNullOrEmpty(version))
        {
            FootText.Text = $"{_service.BaseUri}    v{version}    root: {_service.Root}";
        }
    }

    private async Task LoadOptionsAsync()
    {
        using var doc = await _service.GetAsync("/api/task-options?scope=all");
        if (doc is null || !doc.RootElement.TryGetProperty("tasks", out var tasks))
        {
            return;
        }

        _options.Clear();
        _allTaskNames.Clear();
        foreach (var task in tasks.EnumerateArray())
        {
            var name = Str(task, "name");
            // "=xxx" entries are interface-level groups, not runnable tasks.
            if (string.IsNullOrEmpty(name) || name.StartsWith('='))
            {
                continue;
            }
            var groups = new List<OptionGroup>();
            if (task.TryGetProperty("groups", out var array) && array.ValueKind == JsonValueKind.Array)
            {
                foreach (var group in array.EnumerateArray())
                {
                    groups.Add(ParseGroup(group, name));
                }
            }
            _options[name] = groups;
            _allTaskNames.Add(name);
        }

        _hidden.Clear();
        if (doc.RootElement.TryGetProperty("hidden", out var hidden) && hidden.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in hidden.EnumerateArray())
            {
                _hidden.Add(item.GetString() ?? "");
            }
        }
        _pinned.Clear();
        if (doc.RootElement.TryGetProperty("pinned", out var pinned) && pinned.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in pinned.EnumerateArray())
            {
                _pinned.Add(item.GetString() ?? "");
            }
        }

        RebuildLibrary();
        _signature = "";
        RenderTasks();
        RenderOptions();
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
                    Name = Str(field, "name"),
                    Label = Str(field, "label"),
                    Value = Str(field, "value"),
                });
            }
        }

        return new OptionGroup
        {
            TaskName = taskName,
            Group = Str(element, "group"),
            Type = string.IsNullOrEmpty(Str(element, "type")) ? "select" : Str(element, "type"),
            Depth = Int(element, "depth"),
            Description = Str(element, "description"),
            Label = Str(element, "label"),
            Cases = cases,
            Selected = Int(element, "selected"),
            Fields = fields,
        };
    }

    private void RebuildLibrary()
    {
        var inPlan = new HashSet<string>(_plan.Select(task => task.Name));
        var order = new Dictionary<string, int>();
        for (var i = 0; i < _pinned.Count; i++)
        {
            order[_pinned[i]] = i;
        }

        _library.Clear();
        foreach (var name in _allTaskNames)
        {
            if (inPlan.Contains(name) || _hidden.Contains(name))
            {
                continue;
            }
            _library.Add(new TaskEntry(name, "library"));
        }
        // Pinned entries float to the top in their configured order; everything
        // else keeps the interface order (grouped by category upstream).
        var ordered = _library
            .Select((task, index) => (Task: task, Index: index))
            .OrderBy(item => order.TryGetValue(item.Task.Name, out var rank) ? rank : int.MaxValue)
            .ThenBy(item => item.Index)
            .Select(item => item.Task)
            .ToList();
        _library.Clear();
        _library.AddRange(ordered);
    }

    // ------------------------------------------------------------------ state

    private async Task RefreshAsync()
    {
        // _cursor starts at 0 on purpose: the first poll pulls the tail of the
        // existing log so the pane is not blank while the footer says "成功 8".
        var path = $"/api/state?since={_cursor}";
        using var doc = await _service.GetAsync(path);
        if (doc is null)
        {
            return;
        }

        var root = doc.RootElement;
        _runStatus = Str(root, "status");
        var current = Str(root, "currentTask");
        _busy = Bool(root, "busy");
        _canResume = Bool(root, "canResume");

        var runId = Str(root, "runId");
        if (runId != _runId)
        {
            _runId = runId;
            _logs.Clear();
        }

        _stateTasks.Clear();
        _status.Clear();
        _notes.Clear();
        if (root.TryGetProperty("tasks", out var tasks) && tasks.ValueKind == JsonValueKind.Array)
        {
            foreach (var task in tasks.EnumerateArray())
            {
                var name = Str(task, "name");
                _stateTasks.Add(new TaskEntry(name, Str(task, "kind")));
                var status = Str(task, "status");
                if (!string.IsNullOrEmpty(status))
                {
                    _status[name] = status;
                }
                var note = Str(task, "note");
                if (!string.IsNullOrEmpty(note))
                {
                    _notes[name] = note;
                }
            }
        }

        _singleResults.Clear();
        _singleName = "";
        _singleStatus = "";
        _singleIndex = 0;
        _singleTotal = 0;
        if (root.TryGetProperty("single", out var single) && single.ValueKind == JsonValueKind.Object)
        {
            _singleName = Str(single, "name");
            _singleStatus = Str(single, "status");
            _singleIndex = Int(single, "index");
            _singleTotal = Int(single, "total");
            if (single.TryGetProperty("results", out var results) && results.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in results.EnumerateArray())
                {
                    _singleResults[Str(item, "name")] = Str(item, "status");
                }
            }
        }

        var singleActive = _singleStatus is "pending" or "running";
        var label = StatusLabel(_runStatus);
        StatusText.Text = singleActive
            ? (_singleTotal > 1
                ? $"运行中：{_singleName}（{_singleIndex + 1}/{_singleTotal}）"
                : $"单独运行：{_singleName}")
            : (string.IsNullOrEmpty(current) ? label : $"{label} · {current}");
        StatusDot.Fill = StatusBrush(_runStatus);
        UpdateStep(root);

        if (root.TryGetProperty("config", out var config))
        {
            var serial = Str(config, "adbSerial");
            ConnectionMeta.Text = string.IsNullOrEmpty(serial) ? "" : $"{serial} · 简中";
        }

        ResumeButton.IsEnabled = !_busy && _canResume;
        StopButton.IsEnabled = _busy;
        CheckLink.IsEnabled = !_busy;
        DungeonToggle.IsEnabled = !_busy;
        UpdateStartButton();
        RenderTasksIfChanged();

        var fresh = new List<LogEntry>();
        if (root.TryGetProperty("logs", out var logs) && logs.ValueKind == JsonValueKind.Array)
        {
            foreach (var log in logs.EnumerateArray())
            {
                fresh.Add(new LogEntry
                {
                    Time = Str(log, "time"),
                    Level = Str(log, "level"),
                    Message = Str(log, "message"),
                });
            }
        }
        foreach (var line in fresh)
        {
            _logs.Add(line);
        }
        while (_logs.Count > 800)
        {
            _logs.RemoveAt(0);
        }
        LogEmpty.Visibility = _logs.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        if (_logs.Count > 0)
        {
            LogList.ScrollIntoView(_logs[^1]);
        }

        _cursor = Int(root, "logSeq");
    }

    private static string StatusLabel(string status) => status switch
    {
        "idle" => "待机",
        "starting" => "正在启动",
        "running" => "正在执行",
        "checking" => "正在检查连接",
        "completed" => "日常完成",
        "completed_with_errors" => "完成但有失败",
        "cancelled" => "已停止",
        "error" => "运行异常",
        "interrupted" => "上次未完成",
        _ => status,
    };

    private static Brush StatusBrush(string status) => status switch
    {
        "running" or "checking" or "starting" => BlueBrush,
        "completed" => GreenBrush,
        "completed_with_errors" or "cancelled" or "error" => RedBrush,
        "interrupted" => AmberBrush,
        _ => MutedBrush,
    };

    // ------------------------------------------------------------------ tasks

    private string StatusOf(string name)
    {
        if (_singleResults.TryGetValue(name, out var single))
        {
            return single;
        }
        return _status.TryGetValue(name, out var status) ? status : "";
    }

    private string NoteOf(string name) => _notes.TryGetValue(name, out var note) ? note : "";

    private void RenderTasksIfChanged()
    {
        var rows = _scope == "library" ? _library : VisualDaily();
        var signature = string.Join(
            "\u0001",
            rows.Select(task => $"{task.Name}:{StatusOf(task.Name)}:{NoteOf(task.Name)}:{task.Kind}")
                .Append(_selected)
                .Append(_scope)
                .Append(_dailyChecked.Count.ToString())
                .Append(_libraryChecked.Count.ToString()));
        if (signature == _signature)
        {
            return;
        }
        _signature = signature;
        RenderTasks();
    }

    /// <summary>
    /// While a run is live the server's list is the truth: the plan can name a
    /// different training type than the run was started with (resume, or the
    /// user switched mid-flight), and statuses would silently fail to match.
    /// </summary>
    private List<TaskEntry> VisualDaily()
    {
        if (_busy && _stateTasks.Count > 0)
        {
            // 合并执行时 _stateTasks 里会混进「其他任务」，它们该留在那个页签里。
            var running = _stateTasks.Where(task => task.Kind != "extra").ToList();
            return running.Count > 0 ? running : _stateTasks;
        }
        return _plan.Count > 0 ? _plan : _stateTasks;
    }

    private void RenderTasks()
    {
        TaskListPanel.Children.Clear();
        var rows = _scope == "library" ? _library : VisualDaily();
        DailyCount.Text = VisualDaily().Count.ToString();
        LibraryCount.Text = _library.Count.ToString();

        if (rows.Count == 0)
        {
            TaskListPanel.Children.Add(new TextBlock
            {
                Text = "这一组暂时没有任务。",
                Foreground = MutedBrush,
                FontSize = 12,
                Margin = new Thickness(10, 8, 10, 0),
            });
            return;
        }

        var selectedRow = (FrameworkElement?)null;
        for (var i = 0; i < rows.Count; i++)
        {
            var row = BuildRow(rows[i], i);
            TaskListPanel.Children.Add(row);
            if (rows[i].Name == _selected)
            {
                selectedRow = row;
            }
        }
        selectedRow?.BringIntoView();
        SyncSelectAll();
    }

    private FrameworkElement BuildRow(TaskEntry task, int index)
    {
        var selected = task.Name == _selected;
        var status = StatusOf(task.Name);
        var done = status is "succeeded" or "failed" or "timed_out" or "skipped" or "cancelled";

        var row = new Border
        {
            CornerRadius = new CornerRadius(9),
            BorderThickness = new Thickness(1),
            Padding = new Thickness(10, 9, 10, 9),
            Margin = new Thickness(0, 2, 0, 3),
            Cursor = Cursors.Hand,
            Background = selected ? RowSelectedBrush : RowBrush,
            BorderBrush = selected ? RowSelectedBorder : Brushes.Transparent,
            Opacity = done && !selected ? 0.62 : 1.0,
            Tag = task.Name,
        };

        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

        var bucket = _scope == "library" ? _libraryChecked : _dailyChecked;
        var check = new CheckBox
        {
            IsChecked = bucket.Contains(task.Name),
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, _scope == "library" ? 9 : 6, 0),
            ToolTip = "勾选后点右上角「开始任务」执行",
        };
        check.Checked += (_, _) =>
        {
            bucket.Add(task.Name);
            SyncSelectAll();
            UpdateStartButton();
        };
        check.Unchecked += (_, _) =>
        {
            bucket.Remove(task.Name);
            SyncSelectAll();
            UpdateStartButton();
        };

        FrameworkElement marker;
        if (_scope == "library")
        {
            marker = check;
        }
        else
        {
            // 日常行既要能勾选，也要保留执行序号。
            var strip = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
            };
            strip.Children.Add(check);
            strip.Children.Add(new TextBlock
            {
                Text = (index + 1).ToString("00"),
                Foreground = FaintBrush,
                FontSize = 11,
                Width = 20,
                TextAlignment = TextAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            });
            marker = strip;
        }
        Grid.SetColumn(marker, 0);
        grid.Children.Add(marker);

        var main = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        var failed = status is "failed" or "timed_out";
        main.Children.Add(new TextBlock
        {
            Text = DisplayName(task.Name),
            Foreground = failed ? RedBrush : TextBrush,
            FontSize = 13,
            TextTrimming = TextTrimming.CharacterEllipsis,
        });

        // 「未领取到资源」放第二行行首：跟在任务名后面会被省略号吃掉，
        // 而这句正是这一行最该看见的东西。
        var summary = OptionSummary(task.Name);
        var note = NoteOf(task.Name);
        if (status == "skipped_no_resource" || !string.IsNullOrEmpty(note) || !string.IsNullOrEmpty(summary))
        {
            var sub = new TextBlock
            {
                FontSize = 11,
                Margin = new Thickness(0, 2, 0, 0),
                TextTrimming = TextTrimming.CharacterEllipsis,
            };
            if (status == "skipped_no_resource")
            {
                sub.Inlines.Add(new Run("未领取到资源")
                {
                    FontWeight = FontWeights.Bold,
                    Foreground = AmberBrush,
                });
                if (!string.IsNullOrEmpty(summary))
                {
                    sub.Inlines.Add(new Run(" · " + summary) { Foreground = SubBrush });
                }
            }
            else if (!string.IsNullOrEmpty(note))
            {
                // 例如地宫：「本期未开放」。不如「未领取」那么刺眼，但要能看见，
                // 因为它意味着控制条那个开关可以关掉了。
                sub.Inlines.Add(new Run(note) { Foreground = AmberBrush });
                if (!string.IsNullOrEmpty(summary))
                {
                    sub.Inlines.Add(new Run(" · " + summary) { Foreground = SubBrush });
                }
            }
            else
            {
                sub.Inlines.Add(new Run(summary) { Foreground = SubBrush });
            }
            main.Children.Add(sub);
        }
        Grid.SetColumn(main, 1);
        grid.Children.Add(main);

        var badge = BuildBadge(status, task.Kind);
        if (badge is not null)
        {
            Grid.SetColumn(badge, 2);
            grid.Children.Add(badge);
        }

        row.Child = grid;
        row.MouseLeftButtonUp += (_, _) => SelectTask(task.Name);
        if (!selected)
        {
            row.MouseEnter += (_, _) => row.Background = RowHoverBrush;
            row.MouseLeave += (_, _) => row.Background = RowBrush;
        }
        return row;
    }

    private static FrameworkElement? BuildBadge(string status, string kind)
    {
        if (string.IsNullOrEmpty(status))
        {
            return kind == "seasonal_daily"
                ? Badge("限时", AmberBrush, Frozen(0x5F, 0x4C, 0x2F), FrozenA(0x12, 0xD8, 0xA8, 0x5F))
                : null;
        }

        return status switch
        {
            "succeeded" => Badge("完成", GreenBrush, Frozen(0x33, 0x55, 0x42), FrozenA(0x0F, 0x74, 0xB8, 0x8B)),
            "failed" => Badge("失败", RedBrush, Frozen(0x5C, 0x33, 0x33), FrozenA(0x10, 0xDF, 0x7F, 0x7F)),
            "timed_out" => Badge("超时", AmberBrush, Frozen(0x5F, 0x4C, 0x2F), FrozenA(0x12, 0xD8, 0xA8, 0x5F)),
            "skipped" => Badge("跳过", MutedBrush, Frozen(0x3A, 0x46, 0x58), Brushes.Transparent),
            "cancelled" => Badge("已停止", MutedBrush, Frozen(0x3A, 0x46, 0x58), Brushes.Transparent),
            "skipped_no_resource" => Badge("未领取", AmberBrush, Frozen(0x5F, 0x4C, 0x2F),
                FrozenA(0x12, 0xD8, 0xA8, 0x5F)),
            "running" or "pending" => Badge(TaskStatusLabel(status), BlueBrush, Frozen(0x35, 0x4D, 0x6D),
                FrozenA(0x0F, 0x7F, 0xA7, 0xD9)),
            _ => Badge(TaskStatusLabel(status), MutedBrush, Frozen(0x3A, 0x46, 0x58), Brushes.Transparent),
        };
    }

    private static string TaskStatusLabel(string status) => status switch
    {
        "pending" => "等待",
        "running" => "执行中",
        "skipped_no_resource" => "未领取",
        _ => status,
    };

    private static Border Badge(string text, Brush foreground, Brush border, Brush background) => new()
    {
        // 与开关同一种"圆角矩形"语言；99 会变成胶囊，和深色面板不搭。
        CornerRadius = new CornerRadius(5),
        BorderThickness = new Thickness(1),
        BorderBrush = border,
        Background = background,
        Padding = new Thickness(7, 3, 7, 3),
        VerticalAlignment = VerticalAlignment.Center,
        Margin = new Thickness(8, 0, 0, 0),
        Child = new TextBlock { Text = text, Foreground = foreground, FontSize = 10 },
    };

    private void SelectTask(string name)
    {
        if (name == _selected)
        {
            return;
        }
        _selected = name;
        _signature = "";
        RenderTasks();
        RenderOptions();
    }

    private static bool IsTraining(string name) => Trainings.Any(item => item.TaskName == name);

    private static string DisplayName(string name)
    {
        var match = Trainings.FirstOrDefault(item => item.TaskName == name);
        if (match.TaskName is null)
        {
            return name;
        }
        return name.Split(' ')[0] + " " + "历练";
    }

    private string OptionSummary(string name)
    {
        if (!_options.TryGetValue(name, out var groups))
        {
            return "";
        }
        var primary = new List<string>();
        var secondary = new List<string>();
        foreach (var group in groups)
        {
            if (group.Type == "input" || group.Depth > 0)
            {
                continue;
            }
            if (group.Selected < 0 || group.Selected >= group.Cases.Count)
            {
                continue;
            }
            var value = group.Cases[group.Selected];
            // Raw "Yes"/"No" in a Chinese subtitle reads like a bug; the upstream
            // case names are only meaningful because the row is a switch.
            if (RenderAsSwitch(group))
            {
                secondary.Add(value.Equals("Yes", StringComparison.OrdinalIgnoreCase) ? "开"
                    : value.Equals("No", StringComparison.OrdinalIgnoreCase) ? "关"
                    : value);
            }
            else if (group.Type == "select")
            {
                primary.Add(value);
            }
            else
            {
                secondary.Add(value);
            }
        }
        var parts = primary.Count >= 2 ? primary : primary.Concat(secondary).ToList();
        return string.Join(" · ", parts.Take(3));
    }

    // ---------------------------------------------------------------- options

    private void OnScopeChanged(object sender, RoutedEventArgs e)
    {
        if (!_uiReady)
        {
            return;
        }
        _scope = LibraryTab.IsChecked == true ? "library" : "daily";
        var pool = _scope == "library" ? _library : VisualDaily();
        if (!pool.Any(task => task.Name == _selected) && pool.Count > 0)
        {
            _selected = pool[0].Name;
        }
        _signature = "";
        RenderTasks();
        RenderOptions();
        UpdateStartButton();
    }

    private void RenderOptions()
    {
        OptionsPanel.Children.Clear();
        _buildingPanel = true;
        try
        {
            RenderOptionsCore();
        }
        finally
        {
            _buildingPanel = false;
        }
    }

    private void RenderOptionsCore()
    {
        var inDaily = _plan.Any(task => task.Name == _selected);
        CrumbRoot.Text = string.IsNullOrEmpty(_selected) ? "执行顺序" : (inDaily ? "今日日常" : "其他任务");
        CrumbTitle.Text = string.IsNullOrEmpty(_selected) ? "任务选项" : DisplayName(_selected);

        if (string.IsNullOrEmpty(_selected))
        {
            OptionMeta.Text = "";
            OptionsPanel.Children.Add(EmptyText("从左侧选择一个任务，这里会显示它的可调选项。"));
            return;
        }

        if (IsTraining(_selected))
        {
            OptionsPanel.Children.Add(BuildTrainingRow());
        }

        var groups = _options.TryGetValue(_selected, out var list) ? list : new List<OptionGroup>();
        if (groups.Count == 0)
        {
            OptionMeta.Text = "";
            OptionsPanel.Children.Add(EmptyText("该任务没有可调选项，会按默认设置执行。"));
            OptionsPanel.Children.Add(BuildTip(inDaily));
            return;
        }

        OptionMeta.Text = $"{groups.Count} 项可调";
        foreach (var group in groups)
        {
            OptionsPanel.Children.Add(BuildOptionRow(group));
        }
        OptionsPanel.Children.Add(BuildTip(inDaily));
    }

    private static TextBlock EmptyText(string text) => new()
    {
        Text = text,
        Foreground = MutedBrush,
        FontSize = 12,
        TextWrapping = TextWrapping.Wrap,
        Margin = new Thickness(0, 4, 0, 8),
    };

    private static TextBlock BuildTip(bool inDaily) => new()
    {
        Text = inDaily ? "勾选左侧这一项后，点右上角「开始任务」执行。" : "点右上角「开始任务」单独执行这一项。",
        Foreground = FaintBrush,
        FontSize = 11,
        TextWrapping = TextWrapping.Wrap,
        Margin = new Thickness(0, 14, 0, 0),
    };

    private FrameworkElement BuildTrainingRow()
    {
        var box = new Border
        {
            Background = RowBrush,
            BorderBrush = Frozen(0x29, 0x32, 0x41),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(10, 9, 10, 9),
            Margin = new Thickness(0, 0, 0, 14),
        };

        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var label = new TextBlock
        {
            Text = "历练类型",
            Foreground = MutedBrush,
            FontSize = 12,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 12, 0),
        };
        Grid.SetColumn(label, 0);
        grid.Children.Add(label);

        var buttons = new UniformGrid { Rows = 1, Columns = 3 };
        foreach (var item in Trainings)
        {
            var type = item.Type;
            var button = new RadioButton
            {
                Content = item.Label,
                Style = (Style)FindResource("TrainingTab"),
                GroupName = "training-type",
                IsChecked = type == _training,
                IsEnabled = !_busy,
                Margin = new Thickness(0, 0, type == Trainings[^1].Type ? 0 : 6, 0),
            };
            button.Checked += (_, _) =>
            {
                if (_buildingPanel || type == _training)
                {
                    return;
                }
                _ = ChangeTrainingAsync(type);
            };
            buttons.Children.Add(button);
        }
        Grid.SetColumn(buttons, 1);
        grid.Children.Add(buttons);

        box.Child = grid;
        return box;
    }

    private async Task ChangeTrainingAsync(string type)
    {
        if (_busy)
        {
            return;
        }
        _training = type;
        await _service.PostAsync("/api/settings", new { lastTraining = type });
        SetNotice($"历练类型已切换为「{type}」");
        await LoadPlanAsync();
        _selected = Trainings.FirstOrDefault(item => item.Type == type).TaskName ?? _selected;
        _signature = "";
        RenderTasks();
        RenderOptions();
    }

    private FrameworkElement BuildOptionRow(OptionGroup group)
    {
        var row = new Grid { Margin = new Thickness(group.Depth * 16, 0, 0, 12) };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var label = new StackPanel
        {
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 12, 0),
            MaxWidth = 168,
        };
        label.Children.Add(new TextBlock
        {
            Text = group.Group,
            Foreground = MutedBrush,
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
        });
        if (!string.IsNullOrEmpty(group.Description))
        {
            label.Children.Add(new TextBlock
            {
                Text = group.Description,
                Foreground = FaintBrush,
                FontSize = 11,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 2, 0, 0),
            });
        }
        Grid.SetColumn(label, 0);
        row.Children.Add(label);

        FrameworkElement control;
        if (group.Type == "input")
        {
            control = BuildInput(group);
        }
        else if (RenderAsSwitch(group))
        {
            control = BuildSwitch(group);
        }
        else
        {
            control = BuildSelect(group);
        }
        Grid.SetColumn(control, 1);
        row.Children.Add(control);
        return row;
    }

    private static bool RenderAsSwitch(OptionGroup group) =>
        group.Cases.Count == 2 && group.Type is "switch" or "select";

    private static (int On, int Off) SwitchIndexes(OptionGroup group)
    {
        var on = group.Cases.FindIndex(item => item.Equals("Yes", StringComparison.OrdinalIgnoreCase));
        var off = group.Cases.FindIndex(item => item.Equals("No", StringComparison.OrdinalIgnoreCase));
        return on >= 0 && off >= 0 ? (on, off) : (1, 0);
    }

    private FrameworkElement BuildSelect(OptionGroup group)
    {
        var combo = new ComboBox
        {
            ItemsSource = group.Cases,
            SelectedIndex = Math.Clamp(group.Selected, 0, Math.Max(group.Cases.Count - 1, 0)),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            VerticalAlignment = VerticalAlignment.Center,
        };
        combo.SelectionChanged += async (_, _) =>
        {
            if (_buildingPanel || combo.SelectedIndex < 0)
            {
                return;
            }
            await SaveIndexAsync(group, combo.SelectedIndex);
        };
        return combo;
    }

    private FrameworkElement BuildSwitch(OptionGroup group)
    {
        var indexes = SwitchIndexes(group);
        var isOn = group.Selected == indexes.On;

        var panel = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        var text = new TextBlock
        {
            Text = isOn ? "开" : "关",
            Foreground = isOn ? AccentBrush : MutedBrush,
            FontSize = 12,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(10, 0, 0, 0),
            MinWidth = 16,
        };
        var toggle = new ToggleButton
        {
            Style = (Style)FindResource("SwitchToggle"),
            IsChecked = isOn,
            VerticalAlignment = VerticalAlignment.Center,
        };
        toggle.Click += async (_, _) =>
        {
            if (_buildingPanel)
            {
                return;
            }
            var wanted = toggle.IsChecked == true;
            var ok = await SaveIndexAsync(group, wanted ? indexes.On : indexes.Off);
            if (!ok)
            {
                _buildingPanel = true;
                toggle.IsChecked = !wanted;
                _buildingPanel = false;
                return;
            }
            text.Text = wanted ? "开" : "关";
            text.Foreground = wanted ? AccentBrush : MutedBrush;
        };
        panel.Children.Add(toggle);
        panel.Children.Add(text);
        return panel;
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
                    Foreground = MutedBrush,
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

    private async Task<bool> SaveIndexAsync(OptionGroup group, int index)
    {
        var ok = await _service.PostAsync("/api/task-options", new
        {
            task = group.TaskName,
            group = group.Group,
            index,
        });
        if (ok)
        {
            SetNotice($"已保存：{group.Group}（下次运行生效）");
            // Nested options appear or disappear after a change; reload quietly.
            await LoadOptionsAsync();
        }
        else
        {
            SetNotice(_service.LastMessage ?? "保存失败", true);
        }
        return ok;
    }

    private async Task SaveInputsAsync(OptionGroup group, Dictionary<string, string> values)
    {
        var ok = await _service.PostAsync("/api/task-options", new
        {
            task = group.TaskName,
            group = group.Group,
            inputs = values,
        });
        SetNotice(ok ? $"已保存：{group.Group}（下次运行生效）" : (_service.LastMessage ?? "保存失败"), !ok);
    }

    // ---------------------------------------------------------------- actions

    /// <summary>
    /// 「开始日常」与「开始任务」已经合并：按钮只执行当前列表里勾选的任务。
    /// 日常勾选走 /api/start（保留地宫探测、历练档位、超时表等链上语义），
    /// 其他任务勾选走 /api/run-task。
    /// </summary>
    private void UpdateStartButton()
    {
        // 两个 Tab 的勾选一起算：这个按钮执行的是"你勾的全部任务"，
        // 不只是当前页签。数字只数面板上真的显示出来的项，隐藏任务没份。
        var dailyCount = VisualDaily().Count(task => _dailyChecked.Contains(task.Name));
        var libraryCount = _library.Count(task => _libraryChecked.Contains(task.Name));
        var count = dailyCount + libraryCount;
        StartButton.Content = count > 0 ? $"开始任务（{count}）" : "开始任务";
        StartButton.IsEnabled = !_busy && count > 0;
        StartButton.ToolTip = count > 0
            ? $"今日日常 {dailyCount} 项 · 其他任务 {libraryCount} 项"
            : "先勾选要执行的任务";
        // 表头高度固定：切到「其他任务」时不隐藏，只置灰，避免整栏上下跳。
        DailySelectAll.Visibility = Visibility.Visible;
        DailySelectAll.IsEnabled = _scope != "library";
        if (_scope == "library")
        {
            // 其他任务页没有“全选”的语义；清掉勾选，避免灰框里还带着勾让人误会。
            // 切回日常时 RenderTasks → SyncSelectAll 会按真实状态恢复。
            DailySelectAll.IsChecked = false;
        }
        DailySelectAll.ToolTip = _scope == "library"
            ? "其他任务不支持全选，请逐项勾选"
            : "勾选 / 取消今日日常的全部任务（仅影响当前列表里显示的任务）";
    }

    private void SyncSelectAll()
    {
        if (_scope == "library")
        {
            return;
        }
        var rows = VisualDaily();
        var all = rows.Count > 0 && rows.All(task => _dailyChecked.Contains(task.Name));
        _syncingSelectAll = true;
        DailySelectAll.IsChecked = all;
        _syncingSelectAll = false;
    }

    private void OnDailySelectAll(object sender, RoutedEventArgs e)
    {
        if (_syncingSelectAll || _scope == "library")
        {
            return;
        }
        var rows = VisualDaily();
        // 全选框只有两态：全选 / 全部取消。未开放的地宫、每日进膳根本不在
        // rows 里，自然不受影响（用户 2026-11-07 的要求）。
        var all = rows.Count > 0 && rows.All(task => _dailyChecked.Contains(task.Name));
        if (all)
        {
            foreach (var task in rows)
            {
                _dailyChecked.Remove(task.Name);
            }
        }
        else
        {
            foreach (var task in rows)
            {
                _dailyChecked.Add(task.Name);
            }
        }
        _signature = "";
        RenderTasks();
        SyncSelectAll();
        UpdateStartButton();
    }

    private void SetNotice(string message, bool error = false)
    {
        NoticeText.Text = message;
        NoticeText.Foreground = error ? RedBrush : MutedBrush;
        if (error && !string.IsNullOrEmpty(message))
        {
            // 即时提示会被下一次操作覆盖；失败必须留痕，否则事后无从查起。
            // 服务端 /api/note 会加「界面：」前缀，与运行事件区分开。
            _ = _service.PostAsync("/api/note", new { message, level = "warn" });
        }
    }

    private async void OnStart(object sender, RoutedEventArgs e)
    {
        SetNotice("");
        // 勾选跨两个页签累计：点了这个按钮，两边勾上的都会跑。
        var daily = VisualDaily().Select(task => task.Name).Where(_dailyChecked.Contains).ToList();
        var extra = _library.Select(task => task.Name).Where(_libraryChecked.Contains).ToList();
        if (daily.Count == 0 && extra.Count == 0)
        {
            SetNotice("请先勾选要执行的任务", true);
            return;
        }

        // 只勾了「其他任务」：走独立批量，不覆盖今天的日常进度。
        if (daily.Count == 0)
        {
            var ok = await _service.PostAsync("/api/run-task", new { names = extra });
            SetNotice(
                ok
                    ? $"正在运行 {extra.Count} 项：{string.Join(" → ", extra)}"
                    : (_service.LastMessage ?? "无法启动任务"),
                !ok);
            await RefreshAsync();
            return;
        }

        var started = await _service.PostAsync("/api/start", new
        {
            training = _training,
            dungeon = _dungeon,
            names = daily,
            extra,
        });
        if (!started)
        {
            SetNotice(_service.LastMessage ?? "无法开始任务", true);
        }
        else
        {
            var breakdown = extra.Count > 0
                ? $"（日常 {daily.Count} 项 + 其他 {extra.Count} 项）"
                : "";
            SetNotice(
                $"正在执行 {daily.Count + extra.Count} 项{breakdown}："
                + string.Join(" → ", daily.Concat(extra)));
        }
        await RefreshAsync();
    }

    private async void OnResume(object sender, RoutedEventArgs e)
    {
        SetNotice("");
        var ok = await _service.PostAsync("/api/start", new { training = _training, dungeon = _dungeon, resume = true });
        if (!ok)
        {
            SetNotice(_service.LastMessage ?? "没有可继续的任务", true);
        }
        await RefreshAsync();
    }

    private async void OnStop(object sender, RoutedEventArgs e)
    {
        await _service.PostAsync("/api/stop");
        SetNotice("收到停止请求，正在结束当前任务……");
        await RefreshAsync();
    }

    private async void OnCheck(object sender, RoutedEventArgs e)
    {
        SetNotice("正在检查连接，不会执行游戏任务。");
        var ok = await _service.PostAsync("/api/check");
        if (!ok)
        {
            SetNotice(_service.LastMessage ?? "连接检查未启动", true);
        }
        await RefreshAsync();
    }

    private async void OnDungeonChanged(object sender, RoutedEventArgs e)
    {
        if (_loadingSettings || !_uiReady)
        {
            return;
        }
        if (_busy)
        {
            _loadingSettings = true;
            DungeonToggle.IsChecked = _dungeon;
            _loadingSettings = false;
            return;
        }
        _dungeon = DungeonToggle.IsChecked == true;
        DungeonHint.Text = _dungeon ? "已开启" : "默认关闭";
        await _service.PostAsync("/api/settings", new { lastDungeon = _dungeon });
        await LoadPlanAsync();
        SetNotice(_dungeon ? "地宫已开启，日常顺序已更新。" : "地宫已关闭，日常顺序已更新。");
    }

    private void OnOpenScreenshot(object sender, RoutedEventArgs e)
    {
        if (_service.BaseUri is null)
        {
            return;
        }
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = new Uri(_service.BaseUri, "/api/screenshot").ToString(),
                UseShellExecute = true,
            });
        }
        catch (Exception)
        {
            SetNotice("打开截图失败，可能还没有截图。", true);
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
            startupAction = StartupOptions[StartupCombo.SelectedIndex].Value,
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
            shutdownAction = ShutdownOptions[ShutdownCombo.SelectedIndex].Value,
        });
    }

    // ---------------------------------------------------------------- updates

    private async Task CheckUpdatesAsync()
    {
        try
        {
            using var doc = await _service.GetAsync("/api/updates");
            if (doc is null)
            {
                return;
            }

            var badges = new List<string>();
            var details = new List<string>();
            var downloadRunning = false;

            if (doc.RootElement.TryGetProperty("download", out var download))
            {
                var state = Str(download, "state");
                var message = Str(download, "message");
                var done = Num(download, "doneBytes");
                var total = Num(download, "totalBytes");
                var error = Str(download, "error");

                if (state == "running")
                {
                    downloadRunning = true;
                    _downloadRunning = true;
                    var percent = total > 0 ? $" {done / total * 100:0}%" : "";
                    var size = total > 0 ? $"（{done / 1048576:0}/{total / 1048576:0} MB）" : "";
                    UpdateText.Text = $"正在下载资源{percent}{size}";
                    UpdateBadge.Tag = $"{message}\n{size}\n\n下载在后台进行，不影响当前任务。";
                    UpdateBadge.Background = Frozen(0x14, 0x2A, 0x44);
                    UpdateText.Foreground = BlueBrush;
                    UpdateBadge.Visibility = Visibility.Visible;
                    return;
                }

                if (state == "failed" && !string.IsNullOrEmpty(error))
                {
                    details.Add($"上次更新失败：{error}");
                }
            }

            var staged = Bool(doc.RootElement, "staged");
            var resourceAvailable =
                doc.RootElement.TryGetProperty("resource", out var resource)
                && Bool(resource, "available");
            var frameworkDrifted =
                doc.RootElement.TryGetProperty("framework", out var framework)
                && Bool(framework, "available");

            if (staged)
            {
                badges.Add("资源待生效");
                details.Add("新的资源已经下载并校验完成，关闭 Lite 再打开即生效。");
            }

            if (resourceAvailable)
            {
                if (!staged)
                {
                    badges.Add("资源");
                }
                details.Add($"资源：本地 {Str(resource, "local")} → 上游 {Str(resource, "remote")}（{Str(resource, "remoteDate")}）");
            }

            if (frameworkDrifted)
            {
                // available 现在表示"本地版本与发布包钉住的不一致"，不是"PyPI 有新版"。
                badges.Add("框架版本不一致");
                var latest = Str(framework, "latest");
                details.Add(
                    $"框架：本地 {Str(framework, "installed")}，发布包钉住 {Str(framework, "pinned")}"
                    + (string.IsNullOrEmpty(latest) ? "" : $"，PyPI 最新 {latest}")
                    + "\n框架版本随发布包固定，不提供一键升级。");
            }

            _updateStaged = staged;
            _updateHasResource = resourceAvailable;
            _updateHasFramework = frameworkDrifted;

            if (badges.Count == 0)
            {
                UpdateBadge.Visibility = Visibility.Collapsed;
                _downloadRunning = false;
                return;
            }

            _downloadRunning = downloadRunning;
            UpdateText.Text = "有更新：" + string.Join(" · ", badges);
            UpdateBadge.Background = Frozen(0x2A, 0x24, 0x18);
            UpdateText.Foreground = AmberBrush;
            UpdateBadge.Tag = string.Join("\n", details);
            UpdateBadge.Visibility = Visibility.Visible;
        }
        catch (Exception)
        {
            // Update checks are best-effort; never surface them as a startup error.
        }
    }

    private async void OnUpdateClick(object sender, MouseButtonEventArgs e)
    {
        var details = UpdateBadge.Tag as string ?? "";
        if (_downloadRunning)
        {
            MessageBox.Show(
                details + "\n\n下载完成后会自动校验，下次启动 Lite 生效。",
                "MaaYuan Lite",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        if (_updateStaged)
        {
            var running = _busy ? "\n\n注意：当前有任务正在运行，重启会中断这一轮。" : "";
            var restart = MessageBox.Show(
                details + running + "\n\n现在就重启 Lite 让它生效吗？",
                "MaaYuan Lite",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);
            if (restart == MessageBoxResult.Yes)
            {
                RestartApplication();
            }
            return;
        }

        // 只有框架提示时，这里过去也会问"要不要下载资源"——资源其实已经是最新的。
        if (!_updateHasResource)
        {
            MessageBox.Show(
                details,
                "MaaYuan Lite",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var answer = MessageBox.Show(
            details + "\n\n现在后台下载资源吗？（不影响正在运行的任务）",
            "MaaYuan Lite",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (answer != MessageBoxResult.Yes)
        {
            return;
        }

        var started = await _service.PostAsync("/api/updates/download", new { });
        if (!started)
        {
            MessageBox.Show(
                _service.LastMessage ?? "下载没有启动，稍后再试。",
                "MaaYuan Lite",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
        await CheckUpdatesAsync();
    }

    private static void RestartApplication()
    {
        var path = Environment.ProcessPath;
        if (string.IsNullOrEmpty(path))
        {
            return;
        }
        Process.Start(new ProcessStartInfo
        {
            FileName = path,
            UseShellExecute = true,
            WorkingDirectory = AppContext.BaseDirectory,
        });
        Application.Current.Shutdown();
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

    // ------------------------------------------------------------------ utils

    /// <summary>
    /// 显示流水线当前执行的节点。上游给节点配了 focus 时显示那行中文进度（金色），
    /// 否则退回节点名（等宽、弱化），鼠标悬停看完整节点名以便对照日志。
    /// </summary>
    private void UpdateStep(JsonElement root)
    {
        var node = "";
        var label = "";
        var at = "";
        var focused = false;
        var hasStep = false;

        if (_busy && root.TryGetProperty("step", out var step) && step.ValueKind == JsonValueKind.Object)
        {
            node = Str(step, "node");
            label = Str(step, "label");
            at = Str(step, "at");
            focused = Bool(step, "focus");
            hasStep = node.Length > 0 || label.Length > 0;
        }

        if (!hasStep)
        {
            StepStrip.Visibility = Visibility.Collapsed;
            return;
        }

        StepStrip.Visibility = Visibility.Visible;
        StepText.Text = label.Length > 0 ? label : node;
        StepText.Foreground = (Brush)FindResource(focused ? "AccentBrush" : "MutedBrush");
        StepText.FontFamily = focused ? _uiFont : _monoFont;
        StepText.ToolTip = node.Length > 0 ? node : null;
        StepTime.Text = at;
    }

    private static string Str(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? ""
            : "";

    private static int Int(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Number &&
        value.TryGetInt32(out var number)
            ? number
            : 0;

    private static double Num(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.Number
            ? value.GetDouble()
            : 0;

    private static bool Bool(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.True;

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

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        _timer?.Stop();
        _service.Dispose();
    }
}

using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace MaaYuanLite.Desktop.Services;

/// <summary>
/// Owns the Python backend: locates the bundle, starts it if needed, and exposes
/// the HTTP client. The backend is a child process guarded by --parent-pid, so
/// it exits by itself when this app closes or crashes.
/// </summary>
public sealed class LiteService : IDisposable
{
    private readonly HttpClient _client = new() { Timeout = TimeSpan.FromSeconds(10) };
    private Process? _process;

    public Uri? BaseUri { get; private set; }
    public string Root { get; private set; } = "";
    public string? LastError { get; private set; }

    public async Task<bool> StartAsync(CancellationToken token = default)
    {
        try
        {
            Root = FindRoot();
        }
        catch (Exception error)
        {
            LastError = error.Message;
            return false;
        }

        var portFile = Path.Combine(Root, "runtime", "port.txt");

        // Reuse a backend that is already listening, else start a new one.
        if (await TryExistingAsync(portFile, token))
        {
            return true;
        }

        var python = Path.Combine(Root, "runtime_env", "python", "python.exe");
        if (!File.Exists(python))
        {
            LastError = $"运行时缺失：{python}";
            return false;
        }

        var info = new ProcessStartInfo(python, $"app.py --no-browser --parent-pid {Environment.ProcessId}")
        {
            WorkingDirectory = Root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        _process = Process.Start(info);
        if (_process is null)
        {
            LastError = "无法启动 Python 服务";
            return false;
        }

        for (var attempt = 0; attempt < 100; attempt++)
        {
            token.ThrowIfCancellationRequested();
            await Task.Delay(200, token);
            if (await TryExistingAsync(portFile, token))
            {
                return true;
            }
            if (_process.HasExited)
            {
                LastError = $"服务启动后退出（code={_process.ExitCode}）";
                return false;
            }
        }

        LastError = "等待服务端口超时";
        return false;
    }

    private async Task<bool> TryExistingAsync(string portFile, CancellationToken token)
    {
        if (!File.Exists(portFile))
        {
            return false;
        }
        if (!int.TryParse((await File.ReadAllTextAsync(portFile, token)).Trim(), out var port))
        {
            return false;
        }
        var uri = new Uri($"http://127.0.0.1:{port}");
        try
        {
            using var response = await _client.GetAsync(new Uri(uri, "/api/state?since=latest"), token);
            if (!response.IsSuccessStatusCode)
            {
                return false;
            }
            BaseUri = uri;
            return true;
        }
        catch (HttpRequestException)
        {
            return false;
        }
        catch (TaskCanceledException)
        {
            return false;
        }
    }

    public async Task<JsonDocument?> GetAsync(string path, CancellationToken token = default)
    {
        if (BaseUri is null)
        {
            return null;
        }
        try
        {
            return await _client.GetFromJsonAsync<JsonDocument>(new Uri(BaseUri, path), token);
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            return null;
        }
    }

    public async Task<bool> PostAsync(string path, object? body = null, CancellationToken token = default)
    {
        if (BaseUri is null)
        {
            return false;
        }
        try
        {
            using var content = body is null ? null : JsonContent.Create(body);
            using var response = await _client.PostAsync(new Uri(BaseUri, path), content, token);
            return response.IsSuccessStatusCode;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
        {
            return false;
        }
    }

    private static string FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "app.py")) &&
                Directory.Exists(Path.Combine(dir.FullName, "runtime_env")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        throw new InvalidOperationException("找不到 MaaYuan Lite 根目录（需要 app.py 与 runtime_env/）");
    }

    public void Dispose()
    {
        _client.Dispose();
        if (_process is { HasExited: false })
        {
            // The backend watches our PID, but close it promptly on a clean exit.
            try
            {
                _process.Kill(entireProcessTree: true);
            }
            catch (InvalidOperationException)
            {
            }
        }
        _process?.Dispose();
    }
}

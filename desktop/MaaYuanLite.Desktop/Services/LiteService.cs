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
    public string? LastMessage { get; private set; }

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

        // 必须把管道读空。重定向了却不读，MaaFramework 的日志会把 4 KB 缓冲区
        // 填满，Python 就阻塞在 write 上——表现为任务跑一会儿服务突然不响应。
        // 服务自己的日志在 runtime/lite.log 与 runtime/debug/maa.log，这里丢弃即可。
        _process.OutputDataReceived += (_, _) => { };
        _process.ErrorDataReceived += (_, _) => { };
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();

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

    public string? LastErrorCode { get; private set; }

    public async Task<bool> PostAsync(string path, object? body = null, CancellationToken token = default)
    {
        LastErrorCode = null;
        LastMessage = null;
        if (BaseUri is null)
        {
            return false;
        }
        try
        {
            // StringContent, not JsonContent: JsonContent serialises while the
            // request is being written, so HttpClient cannot set Content-Length
            // and falls back to chunked transfer. app.py reads the body with
            // Content-Length only, so a chunked POST arrives as an empty dict --
            // "task and group are required" every time, with the UI silently
            // treating the save as failed.
            using var content = body is null
                ? null
                : new StringContent(
                    JsonSerializer.Serialize(body, body.GetType()),
                    System.Text.Encoding.UTF8,
                    "application/json");
            using var response = await _client.PostAsync(new Uri(BaseUri, path), content, token);
            if (response.IsSuccessStatusCode)
            {
                return true;
            }
            // Errors carry a stable code plus a message written for the user.
            var text = await response.Content.ReadAsStringAsync(token);
            try
            {
                using var doc = JsonDocument.Parse(text);
                if (doc.RootElement.TryGetProperty("code", out var code))
                {
                    LastErrorCode = code.GetString();
                }
                if (doc.RootElement.TryGetProperty("error", out var message))
                {
                    LastMessage = message.GetString();
                }
            }
            catch (JsonException)
            {
                LastMessage = text;
            }
            return false;
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

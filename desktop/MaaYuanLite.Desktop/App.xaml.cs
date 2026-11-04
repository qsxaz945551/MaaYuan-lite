using System.IO;
using System.Windows;

namespace MaaYuanLite.Desktop;

/// <summary>
/// Interaction logic for App.xaml
/// </summary>
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        // OnLoaded 是 async void：里面任何 await 抛异常都会让进程静默退出，
        // 连事件日志都不留。没有这层捕获，"窗口一闪就没了"完全没法排查。
        DispatcherUnhandledException += (_, args) =>
        {
            LogError("Dispatcher", args.Exception);
            args.Handled = true;
            MessageBox.Show(
                $"界面出错，已记录到 runtime/wpf-error.log：\n\n{args.Exception.Message}",
                "MaaYuan Lite",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            LogError("AppDomain", args.ExceptionObject as Exception);

        base.OnStartup(e);
    }

    private static void LogError(string source, Exception? error)
    {
        if (error is null)
        {
            return;
        }
        try
        {
            var dir = Path.Combine(AppContext.BaseDirectory, "runtime");
            Directory.CreateDirectory(dir);
            var line =
                $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} [{source}] {error.GetType().Name}: {error.Message}\n{error.StackTrace}\n\n";
            File.AppendAllText(Path.Combine(dir, "wpf-error.log"), line);
        }
        catch
        {
            // 记录失败不能再抛，否则递归。
        }
    }
}

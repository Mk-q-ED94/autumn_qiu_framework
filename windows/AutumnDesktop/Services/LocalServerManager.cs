using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Dispatching;

namespace AutumnDesktop.Services;

/// <summary>
/// Auto-launches <c>python -m autumn.server</c> when the configured server URL
/// is local and nothing is already responding — the Windows counterpart of the
/// macOS LocalServerManager, adapted for Windows conventions:
///
/// * interpreter discovery prefers <c>.venv\Scripts\python.exe</c> (Windows venv
///   layout), then the <c>py -3</c> launcher, then <c>python</c> on PATH;
/// * the child process is started with <c>CreateNoWindow</c> so no console flashes;
/// * per-user storage is rooted at <c>%APPDATA%\Autumn</c> via <c>AUTUMN_DATA_DIR</c>
///   (writable without admin, unlike Program Files), and logs at
///   <c>%LOCALAPPDATA%\Autumn\logs</c>.
/// </summary>
public sealed partial class LocalServerManager : ObservableObject, IDisposable
{
    public enum State { Idle, Checking, Starting, RunningManaged, RunningExternal, Unmanaged, Failed }

    [ObservableProperty] private State _status = State.Idle;
    [ObservableProperty] private string _statusText = "未启动";

    private Process? _process;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(1) };
    // Captured at construction (on the UI thread) so off-thread process events
    // can marshal status updates back, mirroring the macOS @MainActor hop.
    private readonly DispatcherQueue? _dispatcher = DispatcherQueue.GetForCurrentThread();

    private const string AppName = "Autumn";

    private void OnUi(Action action)
    {
        if (_dispatcher is null || _dispatcher.HasThreadAccess) action();
        else _dispatcher.TryEnqueue(() => action());
    }

    partial void OnStatusChanged(State value) => StatusText = Describe(value);

    private static string Describe(State s) => s switch
    {
        State.Idle => "未启动",
        State.Checking => "检测中",
        State.Starting => "启动中",
        State.RunningManaged => "已由 App 启动",
        State.RunningExternal => "已连接已有服务",
        State.Unmanaged => "使用外部服务器",
        State.Failed => "启动失败",
        _ => "",
    };

    public async Task StartIfNeededAsync(string rawServerUrl)
    {
        if (!Uri.TryCreate(rawServerUrl, UriKind.Absolute, out var serverUrl))
        {
            Status = State.Failed;
            StatusText = "服务器 URL 无效";
            return;
        }
        if (!CanAutoStart(serverUrl))
        {
            Status = State.Unmanaged;
            return;
        }
        if (_process is { HasExited: false })
            return;

        Status = State.Checking;
        if (await IsHealthyAsync(serverUrl))
        {
            Status = State.RunningExternal;
            return;
        }

        var repoRoot = FindRepositoryRoot();
        if (repoRoot is null)
        {
            Status = State.Failed;
            StatusText = "未找到仓库根目录";
            return;
        }

        try
        {
            StartServer(repoRoot, serverUrl);
            Status = State.Starting;

            for (int i = 0; i < 40; i++)
            {
                await Task.Delay(250);
                if (await IsHealthyAsync(serverUrl))
                {
                    Status = State.RunningManaged;
                    return;
                }
                if (_process is { HasExited: true })
                    break;
            }

            Status = State.Failed;
            StatusText = $"查看 {LogFile()}";
        }
        catch (Exception ex)
        {
            Status = State.Failed;
            StatusText = $"启动失败：{ex.Message}";
        }
    }

    public void Stop()
    {
        if (_process is { HasExited: false } p)
        {
            try { p.Kill(entireProcessTree: true); } catch { /* already gone */ }
        }
        _process = null;
        if (Status is State.RunningManaged or State.Starting)
            Status = State.Idle;
    }

    private void StartServer(string repoRoot, Uri serverUrl)
    {
        var dataDir = DataDir();
        Directory.CreateDirectory(dataDir);
        var logFile = LogFile();
        Directory.CreateDirectory(Path.GetDirectoryName(logFile)!);

        var (exe, prefixArgs) = ResolvePython(repoRoot);

        var psi = new ProcessStartInfo
        {
            FileName = exe,
            WorkingDirectory = repoRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var a in prefixArgs) psi.ArgumentList.Add(a);
        psi.ArgumentList.Add("-m");
        psi.ArgumentList.Add("autumn.server");

        psi.Environment["PYTHONUNBUFFERED"] = "1";
        psi.Environment["AUTUMN_HOST"] = BindHost(serverUrl);
        psi.Environment["AUTUMN_PORT"] = (serverUrl.Port > 0 ? serverUrl.Port : 8765).ToString();
        // Per-user, writable storage location — the framework roots a relative
        // STORAGE_DB_PATH under this (see autumn.core.paths.resolve_data_path).
        psi.Environment["AUTUMN_DATA_DIR"] = dataDir;
        psi.Environment["AUTUMN_ENV_FILE"] = Path.Combine(dataDir, ".env");

        var process = new Process { StartInfo = psi, EnableRaisingEvents = true };

        // Tee stdout/stderr into a rolling launch log so failures are diagnosable.
        var writer = new StreamWriter(new FileStream(logFile, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
        {
            AutoFlush = true,
        };
        writer.WriteLine($"\n--- Autumn server launch {DateTime.Now:O} ---");
        process.OutputDataReceived += (_, e) => { if (e.Data != null) writer.WriteLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) writer.WriteLine(e.Data); };
        process.Exited += (_, _) =>
        {
            writer.Dispose();
            OnUi(() =>
            {
                if (Status is State.RunningManaged or State.Starting)
                    Status = State.Idle;
            });
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        _process = process;
    }

    /// <summary>Pick the Python interpreter, preferring an in-repo venv.</summary>
    private static (string exe, string[] prefixArgs) ResolvePython(string repoRoot)
    {
        var venvPython = Path.Combine(repoRoot, ".venv", "Scripts", "python.exe");
        if (File.Exists(venvPython))
            return (venvPython, Array.Empty<string>());

        // The Windows launcher 'py -3' resolves the newest installed Python 3.
        var pyLauncher = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows), "py.exe");
        if (File.Exists(pyLauncher))
            return (pyLauncher, new[] { "-3" });

        // Fall back to whatever 'python' is on PATH.
        return ("python", Array.Empty<string>());
    }

    private async Task<bool> IsHealthyAsync(Uri serverUrl)
    {
        try
        {
            using var resp = await _http.GetAsync(new Uri(serverUrl, "health"));
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    private static bool CanAutoStart(Uri serverUrl)
    {
        if (!string.Equals(serverUrl.Scheme, "http", StringComparison.OrdinalIgnoreCase)) return false;
        var host = serverUrl.Host.ToLowerInvariant();
        return host is "127.0.0.1" or "localhost" or "::1";
    }

    private static string BindHost(Uri serverUrl)
    {
        var host = serverUrl.Host.ToLowerInvariant();
        return host == "localhost" ? "127.0.0.1" : host;
    }

    private static string DataDir() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), AppName);

    private static string LogFile() =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            AppName, "logs", "autumn_server.log");

    /// <summary>Walk up from the app directory looking for the repo markers.</summary>
    private static string? FindRepositoryRoot()
    {
        // Allow an explicit override (set during development).
        var overridePath = Environment.GetEnvironmentVariable("AUTUMN_REPO_ROOT");
        if (!string.IsNullOrEmpty(overridePath) && IsRepositoryRoot(overridePath))
            return overridePath;

        var dir = AppContext.BaseDirectory;
        for (int i = 0; i < 10 && dir is not null; i++)
        {
            if (IsRepositoryRoot(dir)) return dir;
            dir = Path.GetDirectoryName(dir.TrimEnd(Path.DirectorySeparatorChar));
        }
        return null;
    }

    private static bool IsRepositoryRoot(string dir) =>
        File.Exists(Path.Combine(dir, "pyproject.toml")) &&
        File.Exists(Path.Combine(dir, "autumn", "server", "app.py"));

    public void Dispose()
    {
        Stop();
        _http.Dispose();
    }
}

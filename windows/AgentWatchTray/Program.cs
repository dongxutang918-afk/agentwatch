using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;

namespace AgentWatchTray;

static class Program
{
    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new TrayApp());
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Project path detection — never hardcodes a user directory.
// ─────────────────────────────────────────────────────────────────────────────

static class ProjectLocator
{
    private static string? _cached;
    private static readonly string PersistFile =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                     "AgentWatch", "project_path.txt");

    public static string Find()
    {
        if (_cached != null) return _cached;

        string? found = null;

        // 1. AGENTWATCH_HOME env var.
        found = TryEnv();
        if (found != null) { _cached = found; return found; }

        // 2. Walk up from the exe directory looking for pyproject.toml.
        found = TryWalkUp(AppContext.BaseDirectory);
        if (found != null) { _cached = found; return found; }

        // 3. Walk up from current directory.
        found = TryWalkUp(Directory.GetCurrentDirectory());
        if (found != null) { _cached = found; return found; }

        // 4. Saved preference from a previous successful run.
        found = TrySaved();
        if (found != null) { _cached = found; return found; }

        // 5. Common defaults (only if they actually contain pyproject.toml).
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        foreach (var candidate in new[] {
            Path.Combine(home, "Projects", "agentwatch"),
            Path.Combine(home, "agentwatch"),
        }) {
            if (File.Exists(Path.Combine(candidate, "pyproject.toml"))) {
                _cached = candidate; Persist(candidate); return candidate;
            }
        }

        // 6. Nothing found — ask the user.
        found = AskUser();
        if (found != null) { _cached = found; Persist(found); return found; }

        return "";
    }

    private static string? TryEnv()
    {
        var e = Environment.GetEnvironmentVariable("AGENTWATCH_HOME");
        if (!string.IsNullOrEmpty(e) && File.Exists(Path.Combine(e, "pyproject.toml")))
            return e;
        return null;
    }

    private static string? TryWalkUp(string startDir)
    {
        var dir = startDir;
        for (int i = 0; i < 8; i++)
        {
            if (File.Exists(Path.Combine(dir, "pyproject.toml")))
                return dir;
            var parent = Directory.GetParent(dir);
            if (parent == null) break;
            dir = parent.FullName;
        }
        return null;
    }

    private static string? TrySaved()
    {
        try
        {
            if (File.Exists(PersistFile))
            {
                var saved = File.ReadAllText(PersistFile).Trim();
                if (!string.IsNullOrEmpty(saved) && File.Exists(Path.Combine(saved, "pyproject.toml")))
                    return saved;
            }
        }
        catch { }
        return null;
    }

    private static string? AskUser()
    {
        using var dlg = new FolderBrowserDialog
        {
            Description = "Select the AgentWatch project directory (the one containing pyproject.toml)",
            ShowNewFolderButton = false,
            InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        };
        if (dlg.ShowDialog() != DialogResult.OK) return null;
        var chosen = dlg.SelectedPath;
        if (File.Exists(Path.Combine(chosen, "pyproject.toml")))
            return chosen;
        MessageBox.Show(
            "The selected folder does not contain pyproject.toml.\nPlease select the AgentWatch project root directory.",
            "Invalid Project Directory", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return AskUser(); // recurse
    }

    private static void Persist(string path)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(PersistFile)!);
            File.WriteAllText(PersistFile, path);
        }
        catch { }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// CLI runner — all paths derived from ProjectPath dynamically.
// ─────────────────────────────────────────────────────────────────────────────

static class Cli
{
    public static string ProjectPath { get; set; } = "";
    private static bool _venvWarned = false;

    private static string VenvPython =>
        Path.Combine(ProjectPath, ".venv", "Scripts", "python.exe");
    private static string VenvAgentWatch =>
        Path.Combine(ProjectPath, ".venv", "Scripts", "agentwatch.exe");

    private static string AgentWatchExe =>
        File.Exists(VenvAgentWatch) ? VenvAgentWatch : VenvPython;

    private static string[] AgentWatchArgs(string[] args) =>
        AgentWatchExe.EndsWith("agentwatch.exe")
            ? args
            : new[] { "-m", "agentwatch.cli" }.Concat(args).ToArray();

    /// True when .venv\Scripts\python.exe exists and the CLI is callable.
    public static bool HasVenv =>
        File.Exists(VenvPython);

    public static (string stdout, string stderr, int exitCode)? Run(string[] args, int timeoutSec = 15)
    {
        if (!HasVenv)
        {
            if (!_venvWarned)
            {
                _venvWarned = true;
                var choice = MessageBox.Show(
                    "AgentWatch virtual environment not found.\n\n" +
                    $"Expected: {VenvPython}\n\n" +
                    "Click 'Yes' to automatically set up the Python environment now.\n" +
                    "Click 'No' to skip (you can set it up later from the menu).",
                    "Virtual Environment Missing",
                    MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
                if (choice == DialogResult.Yes)
                {
                    var setupScript = Path.Combine(ProjectPath, "windows", "setup_windows.ps1");
                    var psi = new ProcessStartInfo("powershell.exe",
                        $"-NoExit -ExecutionPolicy Bypass -File \"{setupScript}\"")
                    { WorkingDirectory = ProjectPath, UseShellExecute = true };
                    Process.Start(psi);
                }
            }
            return ("", "venv not found", -1);
        }

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = AgentWatchExe,
                WorkingDirectory = ProjectPath,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var a in AgentWatchArgs(args))
                psi.ArgumentList.Add(a);

            var venvScripts = Path.Combine(ProjectPath, ".venv", "Scripts");
            psi.Environment["PATH"] = $"{venvScripts};{Environment.GetEnvironmentVariable("PATH")}";

            using var proc = Process.Start(psi)!;
            var outTask = proc.StandardOutput.ReadToEndAsync();
            var errTask = proc.StandardError.ReadToEndAsync();

            if (!proc.WaitForExit(timeoutSec * 1000))
            {
                proc.Kill();
                return null;
            }

            return (outTask.Result, errTask.Result, proc.ExitCode);
        }
        catch (Exception ex)
        {
            return ("", ex.Message, -1);
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Status model
// ─────────────────────────────────────────────────────────────────────────────

record EventSummary(
    string Time, string EventType, string Title,
    string Risk, string BodyFirstLine, bool Notified, string Source);

record AppStatus(
    bool BarkOk, string BarkDisplay, bool HooksInstalled, int HookCount,
    string? TaskName, List<string> AllowedPaths, List<string> ForbiddenPaths,
    List<EventSummary> RecentEvents, string Overall, string NotificationMode,
    int PendingApprovals, string PersonaTheme, bool TimeoutWatchNotify,
    bool VenvOk, string ProjectRoot);

// ─────────────────────────────────────────────────────────────────────────────
// Status reader
// ─────────────────────────────────────────────────────────────────────────────

static class StatusReader
{
    public static string ProjectPath { get; set; } = "";

    private static string ReadFile(string relativePath)
    {
        var p = Path.Combine(ProjectPath, relativePath);
        return File.Exists(p) ? File.ReadAllText(p) : "";
    }

    private static JsonObject? ParseJson(string path)
    {
        try
        {
            var text = ReadFile(path);
            if (string.IsNullOrEmpty(text)) return null;
            return JsonNode.Parse(text)?.AsObject();
        }
        catch { return null; }
    }

    private static string MaskKey(string key)
    {
        if (string.IsNullOrEmpty(key) || key == "YOUR_BARK_KEY") return "NOT SET";
        if (key.Length <= 7) return new string('*', key.Length);
        return key[..4] + new string('*', Math.Max(0, key.Length - 7)) + key[^3..];
    }

    public static string SourceLabel(string? source) => source switch
    {
        "pending_pretooluse_timeout"      => "pending",
        "pending_pretooluse_timeout_log_only" => "pending",
        "hook_notification"          => "notification",
        "hook_stop"                  => "stop",
        "hook_pretooluse"            => "pretool",
        "hook_pretooluse_danger"     => "pretool",
        "hook_pretooluse_drift"      => "pretool",
        "hook_posttooluse"           => "posttool",
        "hook_posttooluse_failure"   => "posttool",
        "hook_posttooluse_error"     => "posttool",
        "simulate"                   => "simulate",
        "hook_permission_request"    => "perm-req",
        "hook_permission_denied"     => "perm-denied",
        "" or null                    => "",
        _                            => source ?? "",
    };

    public static AppStatus Read()
    {
        // --- Bark ---
        bool barkOk = false;
        string barkDisplay = "NOT SET";
        string notificationMode = "actionable";
        var config = ParseJson("config.json");
        if (config != null)
        {
            var notifier = config["notifier"]?.AsObject();
            if (notifier != null)
            {
                var key = notifier["bark_key"]?.GetValue<string>() ?? "";
                barkOk = !string.IsNullOrEmpty(key) && key != "YOUR_BARK_KEY";
                barkDisplay = MaskKey(key);
            }
            var np = config["notification_policy"]?.AsObject();
            if (np != null)
                notificationMode = np["mode"]?.GetValue<string>() ?? "actionable";
        }

        // --- Persona ---
        string personaTheme = "off";
        if (config != null)
        {
            var persona = config["persona"]?.AsObject();
            if (persona != null)
            {
                var enabled = persona["enabled"]?.GetValue<bool>() ?? false;
                var theme = persona["theme"]?.GetValue<string>() ?? "off";
                personaTheme = enabled ? theme : "off";
            }
        }

        // --- Approval timeout ---
        bool timeoutWatchNotify = false;
        if (config != null)
        {
            var ad = config["approval_detection"]?.AsObject();
            if (ad != null)
                timeoutWatchNotify = ad["timeout_watch_notify"]?.GetValue<bool>() ?? false;
        }

        // --- Hooks (read-only) ---
        bool hooksInstalled = false;
        int hookCount = 0;
        var claudeSettingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".claude", "settings.json");
        if (File.Exists(claudeSettingsPath))
        {
            try
            {
                var cs = JsonNode.Parse(File.ReadAllText(claudeSettingsPath))?.AsObject();
                var hooks = cs?["hooks"]?.AsObject();
                if (hooks != null)
                {
                    foreach (var evt in new[] { "PreToolUse", "PostToolUse", "Notification",
                                                 "Stop", "PermissionRequest", "PermissionDenied" })
                    {
                        var arr = hooks[evt]?.AsArray();
                        if (arr == null) continue;
                        foreach (var g in arr)
                        {
                            var inner = g?["hooks"]?.AsArray();
                            if (inner == null) continue;
                            foreach (var h in inner)
                            {
                                var cmd = h?["command"]?.GetValue<string>() ?? "";
                                if (cmd.Contains("agentwatch")) { hookCount++; break; }
                            }
                        }
                    }
                    hooksInstalled = (hookCount >= 6);
                }
            }
            catch { }
        }

        // --- Task ---
        string? taskName = null;
        var allowed = new List<string>();
        var forbidden = new List<string>();
        var state = ParseJson("logs/state.json");
        if (state != null)
        {
            var task = state["active_task"]?.AsObject();
            if (task != null)
            {
                taskName = task["name"]?.GetValue<string>();
                allowed = task["allowed_paths"]?.AsArray()
                    ?.Select(n => n?.GetValue<string>() ?? "").Where(s => !string.IsNullOrEmpty(s)).ToList() ?? new();
                forbidden = task["forbidden_paths"]?.AsArray()
                    ?.Select(n => n?.GetValue<string>() ?? "").Where(s => !string.IsNullOrEmpty(s)).ToList() ?? new();
            }
        }

        // --- Pending approvals ---
        int pendingCount = 0;
        try
        {
            var paPath = Path.Combine(ProjectPath, "logs", "pending_actions.json");
            if (File.Exists(paPath))
            {
                var paText = File.ReadAllText(paPath);
                var paArr = JsonNode.Parse(paText)?.AsArray();
                if (paArr != null)
                {
                    foreach (var a in paArr)
                    {
                        var st = a?["status"]?.GetValue<string>() ?? "";
                        if (st == "pending") pendingCount++;
                    }
                }
            }
        }
        catch { pendingCount = -1; }

        // --- Recent events ---
        var recent = new List<EventSummary>();
        var logPath = Path.Combine(ProjectPath, "logs", "agentwatch_events.jsonl");
        if (File.Exists(logPath))
        {
            var lines = File.ReadAllLines(logPath);
            var parsed = new List<JsonObject>();
            foreach (var line in lines.Reverse().Take(50))
            {
                try
                {
                    var obj = JsonNode.Parse(line)?.AsObject();
                    if (obj != null) parsed.Add(obj);
                }
                catch { }
            }
            foreach (var ev in parsed)
            {
                var etype = ev["event_type"]?.GetValue<string>() ?? "info";
                if (etype == "info") continue;
                var ts = ev["timestamp"]?.GetValue<string>() ?? "";
                var time = ts.Length >= 19 ? ts.Substring(11, 8) : "";
                var body = ev["body"]?.GetValue<string>() ?? "";
                var firstLine = body.Split('\n')[0];
                var wasNotified = ev["notified"] != null && ev["notified"]!.GetValue<bool>();
                var source = ev["source"]?.GetValue<string>() ?? "";
                recent.Add(new EventSummary(
                    time, etype,
                    ev["title"]?.GetValue<string>() ?? "",
                    ev["risk"]?.GetValue<string>() ?? "低",
                    firstLine, wasNotified, source));
                if (recent.Count >= 5) break;
            }
        }

        // --- Overall ---
        string overall;
        if (!barkOk) overall = "No Bark Key";
        else if (!ClisVenvOk()) overall = "No .venv";
        else if (!hooksInstalled) overall = "Hooks Missing";
        else if (recent.Any(r => r.EventType is "danger" or "drift" or "failure")) overall = "Recent Risk";
        else overall = "Ready";

        return new AppStatus(barkOk, barkDisplay, hooksInstalled, hookCount,
            taskName, allowed, forbidden, recent, overall, notificationMode,
            pendingCount, personaTheme, timeoutWatchNotify,
            ClisVenvOk(), ProjectPath);
    }

    private static bool ClisVenvOk()
    {
        return File.Exists(Path.Combine(ProjectPath, ".venv", "Scripts", "python.exe"));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Tray application — all paths derived from _projectPath at runtime.
// ─────────────────────────────────────────────────────────────────────────────

sealed class TrayApp : ApplicationContext
{
    private NotifyIcon _tray = null!;
    private SynchronizationContext _syncCtx = null!;
    private string _lastResult = "";
    private string _projectPath = "";

    public TrayApp()
    {
        _projectPath = ProjectLocator.Find();
        if (string.IsNullOrEmpty(_projectPath))
        {
            MessageBox.Show(
                "AgentWatch project directory not found.\n\n" +
                "The project must contain 'pyproject.toml' and 'agentwatch/'.\n\n" +
                "Clone the repo or set AGENTWATCH_HOME environment variable.",
                "AgentWatch -- Project Not Found",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            Environment.Exit(1);
            return;
        }

        _syncCtx = SynchronizationContext.Current!;
        Cli.ProjectPath = _projectPath;
        StatusReader.ProjectPath = _projectPath;

        _tray = new NotifyIcon
        {
            Text = "AgentWatch",
            Visible = true,
            Icon = SystemIcons.Application,
        };
        _tray.ContextMenuStrip = new ContextMenuStrip();

        RebuildMenu();
    }

    // ── Icon helpers ─────────────────────────────────────────────────────

    private static string EventIcon(string type) => type switch
    {
        "danger"                   => "⚠",
        "drift"                    => "↗",
        "failure"                  => "✗",
        "task_done"                => "✓",
        "attention_required"       => "‼",
        "permission_required"      => "‼",
        "permission_denied"        => "✕",
        "possible_permission_wait" => "⏳",
        _                          => "·",
    };

    // ── Menu building ────────────────────────────────────────────────────

    private void RebuildMenu()
    {
        var status = StatusReader.Read();
        _tray.Text = $"AgentWatch - {status.Overall}";

        var menu = new ContextMenuStrip();
        menu.Items.Add(DisabledItem($"AgentWatch -- {status.Overall}"));
        menu.Items.Add(new ToolStripSeparator());

        // Status
        menu.Items.Add(DisabledItem($"Project: {TruncatePath(status.ProjectRoot, 55)}"));
        menu.Items.Add(DisabledItem($"Virtual Env: {(status.VenvOk ? "OK" : "MISSING")}"));
        menu.Items.Add(DisabledItem($"Bark: {(status.BarkOk ? "OK" : status.BarkDisplay)}"));
        var hooksText = status.HooksInstalled ? "Installed" :
            status.HookCount >= 4 ? "Missing PermissionRequest" : "Missing";
        menu.Items.Add(DisabledItem($"Hooks: {hooksText}"));
        menu.Items.Add(DisabledItem($"Notif Mode: {status.NotificationMode}"));
        menu.Items.Add(DisabledItem($"Persona: {PersonaDisplayName(status.PersonaTheme)}"));
        menu.Items.Add(DisabledItem($"Approval Timeout Notify: {(status.TimeoutWatchNotify ? "On" : "Off")}"));

        var paText = status.PendingApprovals switch
        {
            -1 => "Pending approvals: (error)",
            _  => $"Pending approvals: {status.PendingApprovals}",
        };
        menu.Items.Add(DisabledItem(paText));

        if (status.TaskName != null)
        {
            menu.Items.Add(DisabledItem($"Task: {status.TaskName}"));
            if (status.AllowedPaths.Count > 0)
                menu.Items.Add(DisabledItem($"  Allowed: {string.Join(", ", status.AllowedPaths.Take(4))}"));
            if (status.ForbiddenPaths.Count > 0)
                menu.Items.Add(DisabledItem($"  Forbidden: {string.Join(", ", status.ForbiddenPaths.Take(4))}"));
        }
        else
        {
            menu.Items.Add(DisabledItem("Task: (none)"));
        }

        menu.Items.Add(new ToolStripSeparator());

        // Recent Events
        menu.Items.Add(DisabledItem("Recent Events:"));
        if (status.RecentEvents.Count == 0)
            menu.Items.Add(DisabledItem("  (no events yet)"));
        else
            foreach (var ev in status.RecentEvents)
            {
                var tag = ev.Notified ? "notified" : "logged";
                var src = StatusReader.SourceLabel(ev.Source);
                var srcStr = string.IsNullOrEmpty(src) ? "" : $" | {src}";
                menu.Items.Add(DisabledItem(
                    $"  {EventIcon(ev.EventType)} [{ev.Time}] {ev.Title} | {tag}{srcStr}"));
            }

        menu.Items.Add(new ToolStripSeparator());

        // Persona Theme submenu
        var personaSubmenu = new ToolStripMenuItem("Persona Theme");
        var themes = new (string Key, string Name)[]
        {
            ("off", "Off"), ("boss", "总裁版"), ("heir_male", "少爷版"),
            ("heir_female", "大小姐版"), ("emperor", "皇上版"), ("palace", "甄嬛版"),
        };
        var currentTheme = status.PersonaTheme;
        foreach (var (key, name) in themes)
        {
            var item = personaSubmenu.DropDownItems.Add(name, null,
                (_, _) => SetPersonaTheme(key, name));
            if (key == currentTheme)
                ((ToolStripMenuItem)personaSubmenu.DropDownItems[personaSubmenu.DropDownItems.Count - 1])
                    .Checked = true;
        }
        menu.Items.Add(personaSubmenu);
        menu.Items.Add(new ToolStripSeparator());

        // Actions
        menu.Items.Add(ActionItem("Refresh Status", (_, _) => RefreshUI()));
        menu.Items.Add(ActionItem("Add / Update Bark Key...", (_, _) => UpdateBarkKey()));
        menu.Items.Add(ActionItem("Show Bark Config", (_, _) => ShowBarkConfig()));
        menu.Items.Add(ActionItem("Test Push", (_, _) => TestPush()));
        menu.Items.Add(ActionItem("Set Task Boundary...", (_, _) => SetTaskBoundary()));
        menu.Items.Add(ActionItem("Clear Task Boundary", (_, _) => ClearTaskBoundary()));

        menu.Items.Add(new ToolStripSeparator());

        menu.Items.Add(ActionItem("Test Permission Request", (_, _) => TestPermissionRequest()));
        menu.Items.Add(ActionItem("Test Permission Denied", (_, _) => TestPermissionDenied()));
        menu.Items.Add(ActionItem("Test Approval Pending", (_, _) => TestApprovalPending()));
        menu.Items.Add(ActionItem("Test Auto Exec", (_, _) => TestAutoExec()));

        menu.Items.Add(new ToolStripSeparator());

        menu.Items.Add(ActionItem("Preview Current Persona", (_, _) => PreviewPersona()));

        menu.Items.Add(ActionItem("Setup Python Environment", (_, _) => RunSetup()));
        menu.Items.Add(ActionItem("Install / Update Claude Code Hooks", (_, _) => RunHooksInstall()));
        menu.Items.Add(new ToolStripSeparator());

        menu.Items.Add(ActionItem("Open Monitor in PowerShell", (_, _) => OpenMonitor()));
        menu.Items.Add(ActionItem("Open Logs Folder", (_, _) => OpenFolder("logs")));
        menu.Items.Add(ActionItem("Open config.json", (_, _) => OpenFile("config.json")));
        menu.Items.Add(ActionItem("Open README", (_, _) => OpenFile("README.md")));
        menu.Items.Add(ActionItem("Copy Setup Commands", (_, _) => CopySetupCommands()));

        menu.Items.Add(new ToolStripSeparator());

        if (!string.IsNullOrEmpty(_lastResult))
        {
            menu.Items.Add(DisabledItem(_lastResult));
            menu.Items.Add(new ToolStripSeparator());
        }

        menu.Items.Add(ActionItem("Quit", (_, _) =>
        {
            _tray.Visible = false;
            Application.Exit();
        }));

        var oldMenu = _tray.ContextMenuStrip;
        _tray.ContextMenuStrip = menu;
        oldMenu?.Dispose();
    }

    private static string TruncatePath(string p, int max)
    {
        if (p.Length <= max) return p;
        return "..." + p[^(max - 3)..];
    }

    private void RefreshUI(string? result = null)
    {
        if (result != null) _lastResult = result;
        _syncCtx ??= SynchronizationContext.Current;
        _syncCtx?.Post(_ => RefreshUI_OnMain(), null);
    }

    private void RefreshUI_OnMain() => RebuildMenu();

    // ── Persona ───────────────────────────────────────────────────────────

    private static string PersonaDisplayName(string theme) => theme switch
    {
        "off" => "Off", "boss" => "总裁版", "heir_male" => "少爷版",
        "heir_female" => "大小姐版", "emperor" => "皇上版", "palace" => "甄嬛版",
        _ => $"Unknown ({theme})",
    };

    private void SetPersonaTheme(string theme, string name)
    {
        _lastResult = $"Setting persona: {name}...";
        RebuildMenu();
        var args = theme == "off"
            ? new[] { "persona", "off" }
            : new[] { "persona", "set", theme };
        ThreadPool.QueueUserWorkItem(_ =>
        {
            var result = Cli.Run(args, timeoutSec: 10);
            var ok = result?.exitCode == 0;
            if (ok)
                MessageBox.Show($"Persona theme updated: {name}", "Persona Theme Updated",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            else
                MessageBox.Show(result?.stderr ?? "Failed to update persona theme.",
                    "Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            RefreshUI(ok ? $"Persona: {name}" : "Persona update failed.");
        });
    }

    // ── Menu item factories ──────────────────────────────────────────────

    private static ToolStripMenuItem DisabledItem(string text) => new(text) { Enabled = false };

    private static ToolStripMenuItem ActionItem(string text, EventHandler handler)
    {
        var item = new ToolStripMenuItem(text);
        item.Click += handler;
        return item;
    }

    private void RunAsync(string[] args, int timeoutSec = 30,
        string? successMsg = null, string? failMsg = null,
        Action<bool, string?>? onComplete = null)
    {
        ThreadPool.QueueUserWorkItem(_ =>
        {
            var result = Cli.Run(args, timeoutSec: timeoutSec);
            var ok = result?.exitCode == 0;
            var msg = ok ? successMsg : (failMsg ?? result?.stderr ?? "Unknown error");
            var detail = result?.stdout ?? "";
            onComplete?.Invoke(ok, detail);
            RefreshUI(msg);
        });
    }

    // ── Actions ──────────────────────────────────────────────────────────

    private void UpdateBarkKey()
    {
        var input = Microsoft.VisualBasic.Interaction.InputBox(
            "Paste your Bark URL or Bark Key:\n\n" +
            "Examples:\n  https://api.day.app/YOUR_KEY/\n  YOUR_KEY",
            "Add / Update Bark Key", "");
        if (string.IsNullOrWhiteSpace(input)) return;
        _lastResult = "Updating Bark key...";
        RebuildMenu();
        ThreadPool.QueueUserWorkItem(_ =>
        {
            var result = Cli.Run(new[] { "config", "bark", "--value", input });
            var ok = result?.exitCode == 0;
            var outText = result?.stdout ?? "";
            var keyLine = outText.Split('\n')
                .FirstOrDefault(l => l.Contains("key updated") || l.Contains("Bark key"))?.Trim() ?? "";
            if (ok && !string.IsNullOrEmpty(keyLine))
                MessageBox.Show(keyLine, "Bark Key Updated",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            else
                MessageBox.Show(result?.stderr ?? "Failed to update Bark key.",
                    "Error", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            RefreshUI(ok ? "Bark key updated." : "Bark key update failed.");
        });
    }

    private void ShowBarkConfig()
    {
        var status = StatusReader.Read();
        var server = "https://api.day.app";
        try
        {
            var configJson = JsonNode.Parse(
                File.ReadAllText(Path.Combine(_projectPath, "config.json")))?.AsObject();
            var notif = configJson?["notifier"]?.AsObject();
            if (notif != null) server = notif["bark_server"]?.GetValue<string>() ?? server;
        }
        catch { }
        MessageBox.Show(
            $"Bark:  {(status.BarkOk ? "OK" : "Missing")}\n" +
            $"Server: {server}\nKey:   {status.BarkDisplay}",
            "Bark Configuration", MessageBoxButtons.OK, MessageBoxIcon.Information);
    }

    private void TestPush()
    {
        _lastResult = "Testing push...";
        RebuildMenu();
        RunAsync(new[] { "config", "test" },
            successMsg: "Last: Test push sent", failMsg: "Last: Test push failed");
    }

    private void SetTaskBoundary()
    {
        var name = Microsoft.VisualBasic.Interaction.InputBox("Task name:", "Set Task Boundary", "");
        if (string.IsNullOrWhiteSpace(name)) return;
        var allowed = Microsoft.VisualBasic.Interaction.InputBox(
            "Allowed paths (comma-separated):", "Set Task Boundary",
            "tmp_agent_task,figures,results,scripts");
        var forbidden = Microsoft.VisualBasic.Interaction.InputBox(
            "Forbidden paths (comma-separated):", "Set Task Boundary",
            ".env,.git,config.json,agentwatch,pyproject.toml,README.md,install_claude_hooks.sh,uninstall_claude_hooks.sh");
        _lastResult = "Setting task boundary...";
        RebuildMenu();
        RunAsync(new[] { "task", "start", "--name", name, "--allow", allowed ?? "", "--forbid", forbidden ?? "" },
            successMsg: $"Task boundary set: {name}", failMsg: "Failed to set task boundary.");
    }

    private void ClearTaskBoundary()
    {
        _lastResult = "Clearing task boundary...";
        RebuildMenu();
        RunAsync(new[] { "task", "clear" },
            successMsg: "Task boundary cleared.", failMsg: "Failed to clear task boundary.");
    }

    private void TestPermissionRequest()
    {
        _lastResult = "Testing PermissionRequest...";
        RebuildMenu();
        RunAsync(new[] { "simulate", "permission-request" }, timeoutSec: 15,
            successMsg: "PermissionRequest simulated -- check Watch.",
            failMsg: "PermissionRequest test failed -- check logs.");
    }

    private void TestPermissionDenied()
    {
        _lastResult = "Testing PermissionDenied...";
        RebuildMenu();
        RunAsync(new[] { "simulate", "permission-denied" }, timeoutSec: 15,
            successMsg: "PermissionDenied simulated (logged only).",
            failMsg: "PermissionDenied test failed -- check logs.");
    }

    private void PreviewPersona()
    {
        ThreadPool.QueueUserWorkItem(_ =>
        {
            var r1 = Cli.Run(new[] { "persona", "test", "permission" }, timeoutSec: 10);
            var r2 = Cli.Run(new[] { "persona", "test", "done" }, timeoutSec: 10);
            var preview = "Persona Preview\n\n" +
                          "Permission:\n" + (r1?.stdout ?? "(error)") + "\n\n" +
                          "Done:\n" + (r2?.stdout ?? "(error)");
            if (preview.Length > 900) preview = preview[..897] + "...";
            MessageBox.Show(preview, "Persona Preview",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
        });
    }

    private void TestApprovalPending()
    {
        _lastResult = "Testing approval pending...";
        RebuildMenu();
        RunAsync(new[] { "simulate", "approval-pending" }, timeoutSec: 30,
            successMsg: "Approval pending simulation done -- check Watch.",
            failMsg: "Approval pending test failed -- check logs.");
    }

    private void TestAutoExec()
    {
        _lastResult = "Testing auto exec...";
        RebuildMenu();
        RunAsync(new[] { "simulate", "auto-exec" }, timeoutSec: 15,
            successMsg: "Auto exec simulation done -- no notification expected.",
            failMsg: "Auto exec test failed -- check logs.");
    }

    // ── Setup helpers ────────────────────────────────────────────────────

    private void RunSetup()
    {
        var script = Path.Combine(_projectPath, "windows", "setup_windows.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show($"Setup script not found: {script}", "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var psi = new ProcessStartInfo("powershell.exe",
            $"-NoExit -ExecutionPolicy Bypass -File \"{script}\"")
        { WorkingDirectory = _projectPath, UseShellExecute = true };
        Process.Start(psi);
        _lastResult = "Setup script launched in PowerShell.";
        RebuildMenu();
    }

    private void RunHooksInstall()
    {
        var script = Path.Combine(_projectPath, "windows", "install_claude_hooks_windows.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show($"Hooks install script not found: {script}", "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        // Confirm before modifying Claude Code settings.
        var choice = MessageBox.Show(
            "This will install AgentWatch hooks into your Claude Code settings.\n\n" +
            "A backup of settings.json will be created before any changes.\n\n" +
            "Continue?",
            "Install Claude Code Hooks", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
        if (choice != DialogResult.Yes) return;

        var psi = new ProcessStartInfo("powershell.exe",
            $"-NoExit -ExecutionPolicy Bypass -File \"{script}\"")
        { WorkingDirectory = _projectPath, UseShellExecute = true };
        Process.Start(psi);
        _lastResult = "Hooks installation launched in PowerShell.";
        RebuildMenu();
    }

    // ── Open / launch ─────────────────────────────────────────────────────

    private void OpenMonitor()
    {
        var agentwatch = Path.Combine(_projectPath, ".venv", "Scripts", "agentwatch.exe");
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoExit -Command \"cd '{_projectPath}'; & '{agentwatch}' monitor\"",
            UseShellExecute = true,
        };
        try { Process.Start(psi); }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to open PowerShell: {ex.Message}", "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void OpenFolder(string relativePath)
    {
        var path = Path.Combine(_projectPath, relativePath);
        if (Directory.Exists(path))
            Process.Start("explorer.exe", path);
        else
            MessageBox.Show($"Folder not found: {path}", "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private void OpenFile(string relativePath)
    {
        var path = Path.Combine(_projectPath, relativePath);
        if (File.Exists(path))
            Process.Start(new ProcessStartInfo { FileName = path, UseShellExecute = true })?.Dispose();
        else
            MessageBox.Show($"File not found: {path}", "Error",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private void CopySetupCommands()
    {
        var cmds = string.Join("\r\n",
            ":: Step 1 — Install AgentWatch",
            "git clone https://github.com/dongxutang918-afk/agentwatch.git",
            "cd agentwatch",
            "",
            ":: Step 2 — Setup Python environment (or click 'Setup Python Environment' in the tray menu)",
            "powershell -ExecutionPolicy Bypass -File windows\\setup_windows.ps1",
            "",
            ":: Step 3 — Configure Bark key (or click 'Add / Update Bark Key' in the tray menu)",
            ".venv\\Scripts\\agentwatch.exe config bark",
            ".venv\\Scripts\\agentwatch.exe config test",
            "",
            ":: Step 4 — Install hooks (or click 'Install / Update Claude Code Hooks' in the tray menu)",
            "powershell -ExecutionPolicy Bypass -File windows\\install_claude_hooks_windows.ps1");
        Clipboard.SetText(cmds);
        _lastResult = "Setup commands copied to clipboard.";
        RebuildMenu();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _tray?.Dispose();
        base.Dispose(disposing);
    }
}

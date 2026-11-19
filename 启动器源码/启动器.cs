// bboverlay 启动器（C# 版，编译成无窗口 exe）
// 作用：找到 Python → 启动同目录的 bboverlay_gui.py
// 编译：见同目录「编译.ps1」，输出「启动黑匣子叠加工具.exe」
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Launcher
{
    static string Dir;

    static void Msg(string text, string title = "bboverlay")
    {
        MessageBox.Show(text, title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    static bool Exists(string p)
    {
        try { return !String.IsNullOrEmpty(p) && File.Exists(p); }
        catch { return false; }
    }

    // 读 python-path.txt（UTF-8 / UTF-16 都认）
    static string ReadPathFile()
    {
        string f = Path.Combine(Dir, "python-path.txt");
        if (!File.Exists(f)) return null;
        try
        {
            string t = File.ReadAllText(f, Encoding.Unicode).Trim('\uFEFF', '\r', '\n', ' ', '\t');
            if (Exists(t)) return t;
        }
        catch { }
        try
        {
            string t = File.ReadAllText(f, Encoding.UTF8).Trim('\uFEFF', '\r', '\n', ' ', '\t');
            if (Exists(t)) return t;
        }
        catch { }
        return null;
    }

    static string FindPython()
    {
        string p = ReadPathFile();
        if (p != null) return p;

        string la = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string[] cands = {
            Path.Combine(la, @"Programs\Python\Python313\pythonw.exe"),
            Path.Combine(la, @"Programs\Python\Python312\pythonw.exe"),
            Path.Combine(la, @"Programs\Python\Python311\pythonw.exe"),
            @"C:\Python313\pythonw.exe", @"C:\Python312\pythonw.exe", @"C:\Python311\pythonw.exe",
            @"C:\python\pythonw.exe", @"D:\python\pythonw.exe", @"E:\python\pythonw.exe",
            @"D:\Python312\pythonw.exe", @"D:\Python311\pythonw.exe",
            Path.Combine(pf, @"Python312\pythonw.exe"),
            Path.Combine(pf, @"Python311\pythonw.exe")
        };
        foreach (string c in cands) if (Exists(c)) return c;

        // PATH 里找
        try
        {
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string d in path.Split(';'))
            {
                string dd = d.Trim().Trim('"');
                if (dd.Length == 0) continue;
                string c = Path.Combine(dd, "pythonw.exe");
                if (Exists(c)) return c;
            }
        }
        catch { }

        // py 启动器
        try
        {
            foreach (string d in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                string dd = d.Trim().Trim('"');
                if (dd.Length == 0) continue;
                string c = Path.Combine(dd, "py.exe");
                if (Exists(c)) return c;   // 只做兜底，下面会特殊处理
            }
        }
        catch { }
        return null;
    }

    [STAThread]
    static void Main()
    {
        Dir = Path.GetDirectoryName(Application.ExecutablePath);
        if (String.IsNullOrEmpty(Dir)) Dir = Environment.CurrentDirectory;

        string gui = Path.Combine(Dir, "bboverlay_gui.py");
        if (!File.Exists(gui))
        {
            Msg("程序文件不全：找不到 bboverlay_gui.py。\r\n\r\n请把整个文件夹重新解压一遍（不要只拷一部分文件）。");
            return;
        }

        string py = FindPython();
        if (py == null)
        {
            DialogResult r = MessageBox.Show(
                "没有找到 Python，所以界面起不来。\r\n\r\n" +
                "第一次在这台电脑用，请先双击「新电脑配置程序.vbs」，\r\n" +
                "等它显示「配置完成」再双击本启动器。\r\n\r\n" +
                "现在就运行配置程序吗？",
                "bboverlay", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
            if (r == DialogResult.Yes)
            {
                string setup = Path.Combine(Dir, "新电脑配置程序.vbs");
                if (File.Exists(setup))
                {
                    try { Process.Start(new ProcessStartInfo("wscript.exe", "\"" + setup + "\"") { UseShellExecute = false }); }
                    catch (Exception e) { Msg("启动配置程序失败：" + e.Message); }
                }
                else Msg("这个文件夹里没有「新电脑配置程序.vbs」，请重新解压完整程序包。");
            }
            return;
        }

        try
        {
            ProcessStartInfo psi;
            if (Path.GetFileName(py).ToLower() == "py.exe")
                psi = new ProcessStartInfo(py, "-3 \"" + gui + "\"");
            else
                psi = new ProcessStartInfo(py, "\"" + gui + "\"");
            psi.WorkingDirectory = Dir;
            psi.UseShellExecute = false;
            Process.Start(psi);
        }
        catch (Exception e)
        {
            Msg("启动失败：" + e.Message + "\r\n\r\nPython 路径：" + py + "\r\n可以重新双击「新电脑配置程序.vbs」再试。");
        }
    }
}
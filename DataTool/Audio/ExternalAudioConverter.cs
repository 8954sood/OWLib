using System;
using System.Diagnostics;
using System.IO;

namespace DataTool.Audio;

public static class ExternalAudioConverter {
    public static void Convert(Stream input, Stream output, Exception builtInError) {
        string tools = Path.Combine(AppContext.BaseDirectory, "Third Party");
        string vgmstream = Path.Combine(tools, "vgmstream-win", "vgmstream-cli.exe");
        string ffmpeg = Path.Combine(tools, "ffmpeg", "bin", "ffmpeg.exe");
        if (!File.Exists(vgmstream) || !File.Exists(ffmpeg))
            throw new NotSupportedException("Bundled external converters missing", builtInError);
        string work = Path.Combine(Path.GetTempPath(), "owlib-audio-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        try {
            string wem = Path.Combine(work, "input.wem"), wav = Path.Combine(work, "decoded.wav"), ogg = Path.Combine(work, "converted.ogg");
            using (var raw = File.Create(wem)) input.CopyTo(raw);
            Run(vgmstream, new[] { "-i", "-o", wav, wem });
            Run(ffmpeg, new[] { "-hide_banner", "-nostdin", "-loglevel", "error", "-i", wav, "-map", "0:a:0", "-c:a", "libvorbis", "-q:a", "5", "-f", "ogg", ogg });
            using var converted = File.OpenRead(ogg);
            converted.CopyTo(output);
        } catch (Exception externalError) {
            throw new AggregateException("Built-in and external audio conversion failed", builtInError, externalError);
        } finally { Directory.Delete(work, true); }
    }

    private static void Run(string executable, string[] arguments) {
        var start = new ProcessStartInfo(executable) {
            UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardError = true, RedirectStandardOutput = true
        };
        foreach (string argument in arguments) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new IOException("Unable to launch audio converter");
        var stderr = process.StandardError.ReadToEndAsync();
        var stdout = process.StandardOutput.ReadToEndAsync();
        if (!process.WaitForExit(120000)) {
            process.Kill(true);
            process.WaitForExit();
            throw new TimeoutException($"Audio converter exceeded 120 seconds: {Path.GetFileName(executable)}");
        }
        string error = stderr.GetAwaiter().GetResult();
        stdout.GetAwaiter().GetResult();
        if (process.ExitCode != 0) throw new IOException($"{Path.GetFileName(executable)} exited {process.ExitCode}: {error}");
    }
}

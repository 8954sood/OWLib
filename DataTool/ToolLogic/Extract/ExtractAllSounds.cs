using System;
using System.IO;
using System.Linq;
using DataTool.Audio;
using DataTool.Flag;

namespace DataTool.ToolLogic.Extract;

public class AllSoundsFlags : IToolFlags {
    [CLIFlag(Flag = "out-path", NeedsValue = true, Positional = 2, Required = true, Help = "New output directory outside the game installation")]
    public string OutputPath;
    public override bool Validate() => !string.IsNullOrWhiteSpace(OutputPath);
}

[Tool("extract-all-sounds", Description = "Extract all 03F/0B2/0BB audio and embedded 043 bank media; write CSV and browser", CustomFlags = typeof(AllSoundsFlags))]
public class ExtractAllSounds : ITool {
    public static void ValidateOutput(string gameDirectory, string outputDirectory) {
        string game = Path.TrimEndingDirectorySeparator(Path.GetFullPath(gameDirectory));
        string output = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputDirectory));
        if (game.Equals(output, StringComparison.OrdinalIgnoreCase) ||
            output.StartsWith(game + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ||
            game.StartsWith(output + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Output must be outside the game installation and cannot be its ancestor");
        for (var directory = new DirectoryInfo(output); directory != null; directory = directory.Parent) {
            if (directory.Exists && (directory.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("Output ancestry must not contain junctions or symbolic links");
        }
        if (File.Exists(output) || Directory.Exists(output))
            throw new IOException("Use a new output directory for each run; existing output is never overwritten");
    }

    public void Parse(ICLIFlags toolFlags) {
        var flags = (AllSoundsFlags)toolFlags;
        ValidateOutput(Program.Flags.OverwatchDirectory, flags.OutputPath);
        var guids = Program.TrackedFiles.Where(x => x.Key is 0x3F or 0xB2 or 0xBB or 0x43)
            .SelectMany(x => x.Value).Distinct().OrderBy(x => x).ToArray();
        var result = new AudioBatchExporter(flags.OutputPath).Run(guids,
            guid => Program.TankHandler.OpenFile(guid) ?? throw new FileNotFoundException($"Missing game resource {guid:X16}"));
        if (result.Failed > 0) Environment.ExitCode = 2;
    }
}

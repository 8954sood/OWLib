using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using TankLib;

namespace DataTool.Audio;

public sealed class AudioBatchExporter {
    private readonly string output;
    private StreamWriter csv;
    private StreamWriter errors;
    private StreamWriter browserIndex;
    private int success, failed, emptyBanks;
    public record Result(int Success, int Failed, int EmptyBanks);
    public AudioBatchExporter(string outputDirectory) => output = Path.GetFullPath(outputDirectory);

    public Result Run(IEnumerable<ulong> resources, Func<ulong, Stream> open) {
        Directory.CreateDirectory(output);
        using var csvWriter = new StreamWriter(Path.Combine(output, "index.csv"), false, new UTF8Encoding(true)) { AutoFlush = true };
        using var errorWriter = new StreamWriter(Path.Combine(output, "errors.log"), false, Encoding.UTF8) { AutoFlush = true };
        using var jsWriter = new StreamWriter(Path.Combine(output, "audio-index.js"), false, Encoding.UTF8) { AutoFlush = true };
        csv = csvWriter;
        errors = errorWriter;
        browserIndex = jsWriter;
        csv.WriteLine("guid,type,media_id,ordinal,source_bytes,output_bytes,duration_seconds,status,path,error");
        browserIndex.WriteLine("window.OW_AUDIO = [");
        string template = Path.Combine(AppContext.BaseDirectory, "Static", "audio-browser.html");
        File.Copy(template, Path.Combine(output, "browser.html"), false);
        ulong[] guids = resources.Distinct().ToArray();
        int processed = 0;
        foreach (ulong guid in guids) {
            ushort type = teResourceGUID.Type(guid);
            long sourceSize = 0;
            try {
                using Stream stream = open(guid);
                sourceSize = stream.Length;
                if (type == 0x43) {
                    int count = 0;
                    foreach (var media in AudioFormats.ReadBank(stream)) {
                        using var wem = new MemoryStream(media.Bytes, false);
                        Export(guid, type, media.Id.ToString("X8"), media.Ordinal.ToString(CultureInfo.InvariantCulture), wem);
                        count++;
                    }
                    if (count == 0) {
                        emptyBanks++;
                        Record(guid, type, "", "", sourceSize, 0, null, "no_embedded_media", "", "");
                    }
                } else Export(guid, type, "", "", stream);
            } catch (Exception exception) {
                failed++;
                Record(guid, type, "", "", sourceSize, 0, null, "read_failed", "", exception.ToString());
            }
            processed++;
            if (processed % 100 == 0 || processed == guids.Length)
                Console.WriteLine($"[{processed}/{guids.Length} ({100.0 * processed / Math.Max(1, guids.Length):F1}%)] Ogg={success}, failed={failed}, empty banks={emptyBanks}");
        }
        browserIndex.WriteLine("];");
        Console.WriteLine($"Complete: resources={processed}, Ogg={success}, failures={failed}, banks without embedded media={emptyBanks}. Index: {Path.Combine(output, "index.csv")}");
        return new Result(success, failed, emptyBanks);
    }

    private void Export(ulong guid, ushort type, string mediaId, string ordinal, Stream input) {
        string name = $"{guid:X16}.{type:X3}" + (mediaId.Length == 0 ? "" : $"_wem-{mediaId}_{ordinal}");
        string relative = $"{type:X3}/{name}.ogg";
        string destination = Path.Combine(output, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        string temporary = destination + ".partial";
        long size = input.Length;
        try {
            double duration;
            using (var ogg = new FileStream(temporary, FileMode.CreateNew, FileAccess.ReadWrite)) {
                try {
                    AudioFormats.ConvertToOgg(input, ogg);
                    ogg.Flush();
                    duration = AudioFormats.OggDuration(ogg);
                } catch (Exception builtInError) {
                    ogg.SetLength(0);
                    ogg.Position = 0;
                    input.Position = 0;
                    ExternalAudioConverter.Convert(input, ogg, builtInError);
                    ogg.Flush();
                    duration = AudioFormats.OggDuration(ogg);
                }
            }
            File.Move(temporary, destination, false);
            long outputSize = new FileInfo(destination).Length;
            success++;
            Record(guid, type, mediaId, ordinal, size, outputSize, duration, "success", relative, "");
        } catch (Exception exception) {
            if (File.Exists(temporary)) File.Delete(temporary);
            string rawPath = Path.ChangeExtension(relative, ".wem");
            string message = exception.ToString();
            long rawSize = 0;
            try {
                input.Position = 0;
                using var raw = new FileStream(Path.Combine(output, rawPath), FileMode.CreateNew, FileAccess.Write);
                input.CopyTo(raw);
                rawSize = raw.Length;
            } catch (Exception rawError) {
                message += "\nRaw backup failed: " + rawError;
                rawPath = "";
            }
            failed++;
            Record(guid, type, mediaId, ordinal, size, rawSize, null, "conversion_failed", rawPath, message);
        }
    }

    private void Record(ulong guid, ushort type, string mediaId, string ordinal, long sourceSize, long outputSize,
        double? duration, string status, string path, string error) {
        string[] fields = { guid.ToString("X16"), type.ToString("X3"), mediaId, ordinal,
            sourceSize.ToString(CultureInfo.InvariantCulture), outputSize.ToString(CultureInfo.InvariantCulture),
            duration?.ToString("F6", CultureInfo.InvariantCulture) ?? "", status, path, error };
        csv.WriteLine(string.Join(",", fields.Select(x => "\"" + x.Replace("\"", "\"\"") + "\"")));
        browserIndex.WriteLine(JsonSerializer.Serialize(new { guid = fields[0], type = fields[1], mediaId,
            ordinal, sourceSize, outputSize, duration, status, path, error }) + ",");
        if (error.Length != 0) errors.WriteLine($"{DateTimeOffset.UtcNow:O} {fields[0]}.{fields[1]} {mediaId}/{ordinal}: {error}");
    }
}

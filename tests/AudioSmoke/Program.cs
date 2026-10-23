using System.Text;
using DataTool.Audio;
using DataTool.Flag;
using DataTool.ToolLogic.Extract;
using TankLib;
using TACTLib.Core.Product.Tank;
using TACTLib.Core.Product.Tank.CMF;
using TACTLib.Core.Product.Tank.TRG;

static void Assert(bool condition, string message) {
    if (!condition) throw new Exception(message);
}
static byte[] Page(byte[] packet, long granule, byte flags, uint sequence) {
    using var ms = new MemoryStream();
    using var writer = new BinaryWriter(ms);
    writer.Write(Encoding.ASCII.GetBytes("OggS")); writer.Write((byte)0); writer.Write(flags);
    writer.Write(granule); writer.Write(1u); writer.Write(sequence); writer.Write(0u);
    writer.Write((byte)1); writer.Write((byte)packet.Length); writer.Write(packet);
    return ms.ToArray();
}
static byte[] Ogg(bool opus) {
    byte[] packet = new byte[opus ? 19 : 30];
    Encoding.ASCII.GetBytes(opus ? "OpusHead" : "\x01vorbis").CopyTo(packet, 0);
    if (opus) { packet[8] = 1; packet[9] = 2; BitConverter.GetBytes((ushort)312).CopyTo(packet, 10); }
    else BitConverter.GetBytes(48000).CopyTo(packet, 12);
    return Page(packet, 0, 2, 0).Concat(Page(new byte[] { 0 }, opus ? 48312 : 48000, 4, 1)).ToArray();
}
static byte[] Bank(byte[] media) {
    using var ms = new MemoryStream(); using var w = new BinaryWriter(ms);
    w.Write(Encoding.ASCII.GetBytes("DIDX")); w.Write(24u);
    w.Write(42u); w.Write(3u); w.Write((uint)media.Length);
    w.Write(42u); w.Write((uint)(3 + media.Length)); w.Write((uint)media.Length);
    w.Write(Encoding.ASCII.GetBytes("DATA")); w.Write((uint)(3 + 2 * media.Length));
    w.Write(new byte[] { 99, 98, 97 }); w.Write(media); w.Write(media);
    return ms.ToArray();
}
static ulong GuidOf(uint index, ushort type) => new teResourceGUID(index).WithType(type).GUID;

static byte[] OpusWem() {
    using var ms = new MemoryStream(); using var w = new BinaryWriter(ms);
    w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(0u); w.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
    w.Write(36u); w.Write((ushort)0x3041); w.Write((ushort)1); w.Write(48000); w.Write(0);
    w.Write((ushort)0); w.Write((ushort)0); w.Write((ushort)18); w.Write((ushort)0);
    w.Write(1u); w.Write(960); w.Write(1); w.Write((short)0); w.Write((byte)1); w.Write((byte)0);
    w.Write(Encoding.ASCII.GetBytes("seek")); w.Write(2u); w.Write((ushort)3);
    w.Write(Encoding.ASCII.GetBytes("data")); w.Write(3u); w.Write(new byte[] { 0xF8, 0xFF, 0xFE });
    ms.Position = 4; w.Write((uint)(ms.Length - 8)); return ms.ToArray();
}

using (var wem = new MemoryStream(OpusWem()))
using (var ogg = new MemoryStream()) {
    AudioFormats.ConvertToOgg(wem, ogg);
    Assert(Math.Abs(AudioFormats.OggDuration(ogg) - 0.02) < 0.000001, "Actual Wwise Opus conversion writes final EOS page");
}

using (var wav = new MemoryStream())
using (var ogg = new MemoryStream()) {
    using (var w = new BinaryWriter(wav, Encoding.ASCII, true)) {
        w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(36 + 1920); w.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
        w.Write(16); w.Write((ushort)1); w.Write((ushort)1); w.Write(48000); w.Write(96000);
        w.Write((ushort)2); w.Write((ushort)16); w.Write(Encoding.ASCII.GetBytes("data")); w.Write(1920); w.Write(new byte[1920]);
    }
    wav.Position = 0;
    ExternalAudioConverter.Convert(wav, ogg, new NotSupportedException("Synthetic PCM fallback"));
    Assert(Math.Abs(AudioFormats.OggDuration(ogg) - 0.02) < 0.001, "Bundled vgmstream/FFmpeg fallback");
}

foreach (bool opus in new[] { true, false }) {
    using var stream = new MemoryStream(Ogg(opus));
    Assert(Math.Abs(AudioFormats.OggDuration(stream) - 1) < 0.000001, "Ogg duration / Opus pre-skip");
}
using (var bank = new MemoryStream(Bank(Ogg(true)))) {
    var entries = AudioFormats.ReadBank(bank).ToArray();
    Assert(entries.Length == 2 && entries[0].Bytes.SequenceEqual(Ogg(true)), "DIDX offsets and DATA padding");
    Assert(entries[0].Id == entries[1].Id && entries[0].Ordinal != entries[1].Ordinal, "Repeated media ID keeps ordinals");
}
try {
    using var invalid = new MemoryStream(new byte[] { 1, 2, 3 });
    AudioFormats.ReadBank(invalid).ToArray();
    throw new Exception("Truncated bank accepted");
} catch (InvalidDataException) { }

string root = Path.Combine(Path.GetTempPath(), "owlib-audio-smoke-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try {
    string game = Path.Combine(root, "game"); Directory.CreateDirectory(game);
    foreach (string output in new[] { game, Path.Combine(game, "03F"), root }) {
        try { ExtractAllSounds.ValidateOutput(game, output); throw new Exception("Unsafe output accepted"); }
        catch (InvalidOperationException) { }
    }
    string outputPath = Path.Combine(root, "sounds");
    ExtractAllSounds.ValidateOutput(game, outputPath);
    var samples = new Dictionary<ulong, byte[]> {
        [GuidOf(1, 0x3F)] = Ogg(true), [GuidOf(1, 0xB2)] = Ogg(false),
        [GuidOf(2, 0xBB)] = new byte[] { 1, 2, 3 }, [GuidOf(3, 0x43)] = Bank(Ogg(true)),
        [GuidOf(4, 0x43)] = Array.Empty<byte>()
    };
    ulong missing = GuidOf(99, 0x3F);
    var result = new AudioBatchExporter(outputPath).Run(samples.Keys.Append(missing).Append(GuidOf(1, 0x3F)),
        guid => samples.TryGetValue(guid, out var bytes) ? new MemoryStream(bytes) : throw new IOException("synthetic read failure, with comma"));
    Assert(result.Success == 4 && result.Failed == 2 && result.EmptyBanks == 1, "Batch counts / failure isolation / GUID deduplication");
    Assert(Directory.GetFiles(outputPath, "*.ogg", SearchOption.AllDirectories).Length == 4, "Unique output files");
    Assert(Directory.GetFiles(outputPath, "*.wem", SearchOption.AllDirectories).Length == 1, "Raw fallback preserved");
    Assert(Directory.GetFiles(outputPath, "*.partial", SearchOption.AllDirectories).Length == 0, "Partial output removed");
    string csv = File.ReadAllText(Path.Combine(outputPath, "index.csv"));
    Assert(csv.Contains("conversion_failed") && csv.Contains("read_failed") && csv.Contains("no_embedded_media") && csv.Contains("1.000000"), "CSV status and durations");
    Assert(File.ReadAllText(Path.Combine(outputPath, "audio-index.js")).EndsWith("];" + Environment.NewLine), "Offline browser index complete");
    Assert(File.ReadAllText(Path.Combine(outputPath, "errors.log")).Contains("synthetic read failure"), "Error detail retained");
    try { ExtractAllSounds.ValidateOutput(game, outputPath); throw new Exception("Existing output accepted"); } catch (IOException) { }

    DataTool.Program.TrackedFiles = samples.Keys.GroupBy(teResourceGUID.Type).ToDictionary(x => x.Key, x => x.ToHashSet());
    DataTool.Program.Flags = new DataTool.ToolFlags { OverwatchDirectory = game };
    DataTool.Program.TankHandler = null!;
    string commandOutput = Path.Combine(root, "command-output");
    new ExtractAllSounds().Parse(new AllSoundsFlags { OutputPath = commandOutput });
    Assert(File.Exists(Path.Combine(commandOutput, "index.csv")) && Environment.ExitCode == 2, "Actual command reports individual read failures without aborting");
    Environment.ExitCode = 0;
    FlagParser.AppArgs = new[] { game, "extract-all-sounds", Path.Combine(root, "parsed-output") };
    var flags = FlagParser.Parse<AllSoundsFlags>();
    Assert(flags != null && flags.OutputPath.EndsWith("parsed-output"), "CLI positional parsing");
    Assert(DataTool.Program.GetTools().Contains(typeof(ExtractAllSounds)), "Command discovered via Tool attribute");
} finally { Directory.Delete(root, true); }

var cmf = new ProCMF_154504(); var trg = new ProTRG_154504();
var cmfHeader = new ContentManifestFile.CMFHeader { m_buildVersion = 154504, m_dataCount = 123 };
var trgHeader = new ResourceGraph.TRGHeader { m_buildVersion = 154504, m_packageCount = 123 };
byte[] digest = Enumerable.Range(0, 20).Select(x => (byte)x).ToArray();
Assert(cmf.Key(cmfHeader, 32).SequenceEqual(trg.Key(trgHeader, 32)), "CMF/TRG shared key derivation");
Assert(cmf.IV(cmfHeader, digest, 16).SequenceEqual(trg.IV(trgHeader, digest, 16)), "CMF/TRG equal-count IV derivation");
Assert(cmf.Key(cmfHeader, 32).Length == 32 && cmf.IV(cmfHeader, digest, 16).Length == 16, "AES key/IV lengths");
Console.WriteLine("PASS: audio containers, bank offsets, durations, batch errors, CLI registration/execution, output safety, crypto shape. Synthetic resources only; no real game extraction verified.");

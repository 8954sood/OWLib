using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using DataTool.ConvertLogic.WEM;
using DataTool.SaveLogic;
using RevorbStd;

namespace DataTool.Audio;

public static class AudioFormats {
    public record BankMedia(uint Id, int Ordinal, byte[] Bytes);

    public static IEnumerable<BankMedia> ReadBank(Stream stream) {
        using var reader = new BinaryReader(stream, Encoding.ASCII, true);
        long dataStart = -1;
        uint dataSize = 0;
        var entries = new List<(uint Id, uint Offset, uint Size)>();
        stream.Position = 0;
        while (stream.Position < stream.Length) {
            if (stream.Length - stream.Position < 8) throw new InvalidDataException("Truncated bank chunk");
            string tag = Encoding.ASCII.GetString(reader.ReadBytes(4));
            uint size = reader.ReadUInt32();
            long end = checked(stream.Position + size);
            if (end > stream.Length) throw new InvalidDataException("Bank chunk exceeds file");
            if (tag == "DATA") {
                dataStart = stream.Position;
                dataSize = size;
            } else if (tag == "DIDX") {
                if (size % 12 != 0) throw new InvalidDataException("Invalid DIDX size");
                while (stream.Position < end) entries.Add((reader.ReadUInt32(), reader.ReadUInt32(), reader.ReadUInt32()));
            }
            stream.Position = end;
        }
        if (entries.Count > 0 && dataStart < 0) throw new InvalidDataException("DIDX without DATA");
        for (int i = 0; i < entries.Count; i++) {
            var entry = entries[i];
            if ((ulong)entry.Offset + entry.Size > dataSize || entry.Size > int.MaxValue)
                throw new InvalidDataException($"Invalid DIDX media range at {i}");
            stream.Position = dataStart + entry.Offset;
            byte[] bytes = reader.ReadBytes((int)entry.Size);
            if (bytes.Length != entry.Size) throw new EndOfStreamException();
            yield return new BankMedia(entry.Id, i, bytes);
        }
    }

    public static void ConvertToOgg(Stream input, Stream output) {
        using var reader = new BinaryReader(input, Encoding.ASCII, true);
        input.Position = 0;
        string magic = Encoding.ASCII.GetString(reader.ReadBytes(4));
        input.Position = 0;
        if (magic == "OggS") {
            input.CopyTo(output);
            return;
        }
        if (magic != "RIFF" || input.Length < 12) throw new InvalidDataException("Expected Wwise RIFF/WAVE or Ogg");
        input.Position = 8;
        if (Encoding.ASCII.GetString(reader.ReadBytes(4)) != "WAVE") throw new InvalidDataException("Not WAVE");
        ushort codec = 0;
        while (input.Position < input.Length) {
            if (input.Length - input.Position < 8) throw new InvalidDataException("Truncated RIFF chunk");
            string tag = Encoding.ASCII.GetString(reader.ReadBytes(4));
            uint size = reader.ReadUInt32();
            long end = checked(input.Position + size);
            if (end > input.Length) throw new InvalidDataException("RIFF chunk exceeds file");
            if (tag == "fmt ") {
                if (size < 2) throw new InvalidDataException("Truncated fmt chunk");
                codec = reader.ReadUInt16();
                break;
            }
            input.Position = end + (size & 1);
        }
        input.Position = 0;
        if (codec == 0xFFFF) {
            using var wem = new WwiseRIFFVorbis(new LeaveOpenReadStream(input), Path.Combine(AppContext.BaseDirectory, "Third Party", "packed_codebooks_aoTuV_603.bin"));
            using var converted = new MemoryStream();
            wem.ConvertToOgg(converted);
            converted.Position = 0;
            using var repaired = Revorb.Jiggle(converted);
            CopyOggThroughEnd(repaired, output);
        }
        else if (codec == 0x3041) {
            using var opus = new WwiseRIFFOpus(input, false);
            opus.ConvertToOgg(output);
        } else throw new NotSupportedException($"Wwise codec 0x{codec:X4}: built-in conversion unavailable; raw WEM retained");
    }

    public static void CopyOggThroughEnd(Stream input, Stream output) {
        input.Position = 0;
        using var reader = new BinaryReader(input, Encoding.ASCII, true);
        while (true) {
            byte[] header = reader.ReadBytes(27);
            if (header.Length != 27 || Encoding.ASCII.GetString(header, 0, 4) != "OggS")
                throw new InvalidDataException("Invalid Ogg page before end of stream");
            byte[] segments = reader.ReadBytes(header[26]);
            if (segments.Length != header[26]) throw new EndOfStreamException();
            int length = 0;
            foreach (byte segment in segments) length += segment;
            byte[] payload = reader.ReadBytes(length);
            if (payload.Length != length) throw new EndOfStreamException();
            output.Write(header);
            output.Write(segments);
            output.Write(payload);
            if ((header[5] & 4) != 0) return;
        }
    }

    private sealed class LeaveOpenReadStream(Stream inner) : Stream {
        public override bool CanRead => inner.CanRead;
        public override bool CanSeek => inner.CanSeek;
        public override bool CanWrite => false;
        public override long Length => inner.Length;
        public override long Position { get => inner.Position; set => inner.Position = value; }
        public override int Read(byte[] buffer, int offset, int count) => inner.Read(buffer, offset, count);
        public override long Seek(long offset, SeekOrigin origin) => inner.Seek(offset, origin);
        public override void Flush() { }
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    public static double OggDuration(Stream stream) {
        using var reader = new BinaryReader(stream, Encoding.ASCII, true);
        stream.Position = 0;
        int sampleRate = 0, preSkip = 0;
        long lastGranule = -1;
        uint? serial = null;
        bool eos = false;
        using var firstPacket = new MemoryStream();
        while (stream.Position < stream.Length) {
            if (stream.Length - stream.Position < 27 || Encoding.ASCII.GetString(reader.ReadBytes(4)) != "OggS")
                throw new InvalidDataException("Invalid Ogg page");
            if (reader.ReadByte() != 0) throw new InvalidDataException("Unsupported Ogg version");
            byte flags = reader.ReadByte();
            long granule = reader.ReadInt64();
            uint pageSerial = reader.ReadUInt32();
            serial ??= pageSerial;
            if (pageSerial != serial) throw new InvalidDataException("Chained/multiplexed Ogg requires external inspection");
            reader.ReadUInt32();
            reader.ReadUInt32();
            int segments = reader.ReadByte();
            byte[] lacing = reader.ReadBytes(segments);
            if (lacing.Length != segments) throw new EndOfStreamException();
            foreach (byte length in lacing) {
                byte[] bytes = reader.ReadBytes(length);
                if (bytes.Length != length) throw new EndOfStreamException();
                if (sampleRate != 0) continue;
                firstPacket.Write(bytes);
                if (firstPacket.Length > 65536) throw new InvalidDataException("Ogg identification packet too large");
                if (length == 255) continue;
                byte[] packet = firstPacket.ToArray();
                if (packet.Length >= 19 && Encoding.ASCII.GetString(packet, 0, 8) == "OpusHead") {
                    sampleRate = 48000;
                    preSkip = packet[10] | packet[11] << 8;
                } else if (packet.Length >= 30 && packet[0] == 1 && Encoding.ASCII.GetString(packet, 1, 6) == "vorbis") {
                    sampleRate = System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(packet.AsSpan(12, 4));
                } else throw new InvalidDataException("Unknown Ogg audio identification");
                if (sampleRate <= 0) throw new InvalidDataException("Invalid Ogg sample rate");
            }
            if (granule >= 0) lastGranule = granule;
            eos |= (flags & 4) != 0;
        }
        if (!eos || sampleRate == 0 || lastGranule < preSkip) throw new InvalidDataException("Incomplete Ogg audio");
        return (lastGranule - preSkip) / (double)sampleRate;
    }
}

using System.IO;
using System.Text.Json;
using MapleLib.WzLib;

// GPL-3.0-only. Directory/header inspection only; never call ParseImage or decode pixels.
internal static class ArtworkIndex
{
    private static readonly Dictionary<string, string[]> Wanted = new()
    {
        ["Tile"] = new[] { "tile_whiteMarble.img" },
        ["Obj"] = new[] { "obj_acc1.img", "obj_connect.img", "obj_housePT.img",
            "obj_signboard.img", "obj_vehicle.img" },
        ["Back"] = new[] { "back_grassySoil.img", "back_portTown.img" }
    };

    private static string Safe(string path)
    {
        path = Path.GetFullPath(path);
        for (var current = path; current != null; current = Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current))
                && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Reparse paths forbidden");
        return path;
    }

    private static IEnumerable<string> Matches(WzDirectory directory, HashSet<string> wanted,
        string prefix, ref int budget)
    {
        // No image property access: WzImages is the parsed directory's lazy image table.
        if (--budget < 0) throw new InvalidDataException("Directory budget exceeded");
        var result = new List<string>();
        foreach (var image in directory.WzImages)
        {
            if (--budget < 0) throw new InvalidDataException("Image-index budget exceeded");
            if (wanted.Contains(image.Name)) result.Add(prefix + image.Name);
        }
        foreach (var child in directory.WzDirectories)
            result.AddRange(Matches(child, wanted, prefix + child.Name + "/", ref budget));
        return result;
    }

    internal static int Run(string mapRoot, string output)
    {
        mapRoot = Safe(mapRoot);
        output = Safe(output);
        if (File.Exists(output) || Directory.Exists(output)) throw new IOException("Output exists");
        if (output.StartsWith(mapRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Output must stay outside installed artwork");
        var records = new List<object>();
        foreach (var (category, names) in Wanted)
        foreach (var canvas in new[] { false, true })
        {
            var folder = Safe(Path.Combine(mapRoot, category, canvas ? "_Canvas" : ""));
            var stem = canvas ? "_Canvas" : category;
            var ini = Safe(Path.Combine(folder, stem + ".ini"));
            if (new FileInfo(ini).Length > 4096) throw new InvalidDataException("Index metadata budget");
            var text = File.ReadAllText(ini).Trim();
            var parts = text.Split('|');
            if (parts.Length != 2 || parts[0] != "LastWzIndex"
                || !int.TryParse(parts[1], out var last) || last < 0 || last > 32)
                throw new InvalidDataException("Unsupported archive index");
            for (var index = 0; index <= last; index++)
            {
                var path = Safe(Path.Combine(folder, $"{stem}_{index:D3}.wz"));
                var before = new FileInfo(path);
                var length = before.Length;
                var modified = before.LastWriteTimeUtc.Ticks;
                if (length > 256 * 1024 * 1024) throw new InvalidDataException("Archive size budget");
                // Fixed BMS/779 conventions observed in the pinned copies. No executable/key discovery.
                using var file = new WzFile(path, 779, WzMapleVersion.BMS);
                if (file.ParseWzFile() != WzFileParseStatus.Success)
                    throw new InvalidDataException($"Cannot read directory index: {path}");
                var budget = 100000;
                var matches = Matches(file.WzDirectory, names.ToHashSet(), "", ref budget)
                    .OrderBy(value => value, StringComparer.Ordinal).ToArray();
                var after = new FileInfo(path);
                if (after.Length != length || after.LastWriteTimeUtc.Ticks != modified)
                    throw new InvalidDataException("Archive changed during index read");
                records.Add(new { path, category, canvas, bytes = length,
                    modified_utc_ticks = modified, index_file = ini, index_text = text,
                    locale = "BMS", archive_version = 779, matching_images = matches,
                    image_properties_parsed = false, pixels_decoded = false });
            }
        }
        var report = new { schema = 1, map_id = "000000060", archives = records,
            scope = "Installed artwork directory indexes and headers only",
            bitmap_link_closure_verified = false, native_acceptance = false, input_sent = false };
        using var handle = new FileStream(output, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(handle, report, new JsonSerializerOptions { WriteIndented = true });
        return 0;
    }
}

using System.IO;
using System.Text.Json;
using MapleLib.WzLib;
using MapleLib.WzLib.Util;
using MapleLib.WzLib.WzProperties;

// GPL-3.0-only: this separate offline tool links MapleLib. Never loaded by the bot.
internal static class Program
{
    private const int MaxNodes = 100000;
    private static int nodes;
    private static readonly Dictionary<string, WzFile> files = new(StringComparer.Ordinal);
    private static readonly List<object> archives = new();

    private static object? Dump(WzImageProperty? property, int depth = 0)
    {
        if (++nodes > MaxNodes || depth > 32) throw new InvalidDataException("Property budget exceeded");
        if (property == null) return null;
        if (property is WzUOLProperty uol)
            return new { type = "uol", value = uol.Value };
        if (property is WzVectorProperty vector)
            return new { type = "vector", x = vector.X.Value, y = vector.Y.Value };
        if (property is WzCanvasProperty canvas)
            return new { type = "canvas", width = canvas.PngProperty.Width,
                height = canvas.PngProperty.Height, format = (int)canvas.PngProperty.Format,
                properties = canvas.WzProperties.ToDictionary(p => p.Name, p => Dump(p, depth + 1)) };
        if (property.WzProperties != null)
            return property.WzProperties.ToDictionary(p => p.Name, p => Dump(p, depth + 1));
        if (property.WzValue is byte[]) throw new InvalidDataException("Unsupported binary property");
        var value = property.WzValue;
        if (value is string text && text.Length > 4096)
            throw new InvalidDataException("String property budget exceeded");
        return value;
    }

    private static IEnumerable<WzImage> Find(WzDirectory directory, string name, int depth = 0)
    {
        if (depth > 16 || ++nodes > MaxNodes) throw new InvalidDataException("Directory budget exceeded");
        foreach (var image in directory.WzImages)
            if (image.Name == name) yield return image;
        foreach (var child in directory.WzDirectories)
            foreach (var image in Find(child, name, depth + 1)) yield return image;
    }

    private static WzImage Image(string archive, string name)
    {
        if (!files.TryGetValue(archive, out var file))
            throw new InvalidDataException($"Unreceipted link archive: {archive}");
        var matches = Find(file.WzDirectory, name).Take(2).ToArray();
        if (matches.Length != 1) throw new InvalidDataException($"Missing/ambiguous image: {name}");
        matches[0].ParseImage();
        return matches[0];
    }

    private static WzImageProperty At(WzImage image, string path)
    {
        WzImageProperty? property = null;
        foreach (var part in path.Split('/'))
        {
            if (part is "" or "." or ".." || part.Contains('\\') || part.Contains(':'))
                throw new InvalidDataException("Unsafe property path");
            if (property is WzUOLProperty) throw new InvalidDataException("Unsupported UOL traversal");
            property = property == null ? image[part] : property[part];
            if (property == null) throw new InvalidDataException($"Missing property: {path}");
        }
        return property!;
    }

    private static object ExportCanvas(string archive, string imageName, string path,
        string output, string name)
    {
        var chain = new List<object>();
        var seen = new HashSet<string>();
        for (var depth = 0; depth < 16; depth++)
        {
            var identity = $"{archive}/{imageName}/{path}";
            if (!seen.Add(identity)) throw new InvalidDataException("Canvas link cycle");
            var property = At(Image(archive, imageName), path);
            if (property is not WzCanvasProperty canvas)
                throw new InvalidDataException("Unsupported canvas/UOL target");
            var external = canvas.WzProperties.FirstOrDefault(p => p.Name == "_outlink");
            var local = canvas.WzProperties.FirstOrDefault(p => p.Name == "_inlink");
            if (external != null && local != null) throw new InvalidDataException("Ambiguous canvas link");
            chain.Add(new { archive, image = imageName, property = path, metadata = Dump(canvas) });
            if (external != null)
            {
                var target = (string)external.WzValue;
                var parts = target.Split('/');
                if (parts.Any(p => p is "" or "." or ".." || p.Contains('\\') || p.Contains(':')))
                    throw new InvalidDataException("Unsafe outlink");
                var split = Array.FindIndex(parts, p => p.EndsWith(".img", StringComparison.Ordinal));
                if (split < 1 || split == parts.Length - 1) throw new InvalidDataException("Invalid outlink");
                var prefix = string.Join('/', parts.Take(split));
                var candidates = files.Keys.Where(k => k.StartsWith(prefix + "/", StringComparison.Ordinal)
                    && !k[(prefix.Length + 1)..].Contains('/')).ToArray();
                if (candidates.Length != 1) throw new InvalidDataException("Missing/ambiguous outlink archive");
                archive = candidates[0];
                imageName = parts[split];
                path = string.Join('/', parts.Skip(split + 1));
                continue;
            }
            if (local != null) { path = (string)local.WzValue; continue; }
            var png = canvas.PngProperty;
            if ((int)png.Format != 1 || png.Width <= 0 || png.Height <= 0
                || (long)png.Width * png.Height > 1000000)
                throw new InvalidDataException("Unsupported canvas format/size");
            var compressed = png.GetCompressedBytes(false);
            if (compressed.Length > 8000000) throw new InvalidDataException("Compressed image budget");
            File.WriteAllBytes(Path.Combine(output, name + ".compressed.bin"), compressed);
            using var bitmap = png.GetImage(false);
            bitmap.Save(Path.Combine(output, name + ".png"), System.Drawing.Imaging.ImageFormat.Png);
            return new { width = png.Width, height = png.Height, format = (int)png.Format, chain };
        }
        throw new InvalidDataException("Canvas link depth exceeded");
    }

    private static int TraceArtwork(string root, string references, string output)
    {
        if (File.Exists(output) || Directory.Exists(output)) throw new IOException("Output exists");
        using var request = JsonDocument.Parse(File.ReadAllText(references));
        if (request.RootElement.GetProperty("map_id").GetString() != "000000060")
            throw new InvalidDataException("Southperry references only");
        var queue = new Queue<(string Image, string Property, int Depth)>();
        var allowed = new Dictionary<string, string>();
        foreach (var category in new[] { "Tile", "Obj", "Back" })
        {
            var archive = $"Map/{category}/{category}_000.wz";
            var file = new WzFile(Path.Combine(root, archive), 779, WzMapleVersion.BMS);
            files.Add(archive, file);
            if (file.ParseWzFile() != WzFileParseStatus.Success)
                throw new InvalidDataException($"Cannot parse copied artwork: {archive}");
            allowed.Add($"Map/{category}", archive);
        }
        foreach (var row in request.RootElement.GetProperty("core_scenery").EnumerateArray())
            foreach (var entry in row.GetProperty("entries").EnumerateArray())
                queue.Enqueue((row.GetProperty("image").GetString()!, entry.GetString()!, 0));
        var visited = new HashSet<string>();
        var branches = new List<object>();
        var links = new List<object>();
        var canvases = new List<object>();
        string Normalize(string path)
        {
            var result = new List<string>();
            foreach (var part in path.Split('/'))
            {
                if (part == "..")
                {
                    if (result.Count == 0) throw new InvalidDataException("UOL escapes image");
                    result.RemoveAt(result.Count - 1);
                }
                else if (part != ".")
                {
                    if (part.Length == 0 || part.Contains('\\') || part.Contains(':'))
                        throw new InvalidDataException("Unsafe artwork path");
                    result.Add(part);
                }
            }
            return string.Join('/', result);
        }
        void Scan(WzImageProperty property, string image, string path, int depth, int treeDepth = 0)
        {
            if (treeDepth > 32 || ++nodes > MaxNodes)
                throw new InvalidDataException("Artwork property budget exceeded");
            string? kind = null, target = null;
            if (property is WzUOLProperty uol)
            {
                kind = "uol";
                var parent = path.Contains('/') ? path[..path.LastIndexOf('/')] + "/" : "";
                target = image + "/" + Normalize(parent + uol.Value);
            }
            else if (property is WzCanvasProperty canvas)
            {
                var props = canvas.WzProperties;
                var declaredLinks = props.Where(p => p.Name is "_outlink" or "_inlink").ToArray();
                if (declaredLinks.Length > 1) throw new InvalidDataException("Ambiguous canvas links");
                if (declaredLinks.Length == 1)
                {
                    kind = declaredLinks[0].Name == "_outlink" ? "outlink" : "inlink";
                    target = (kind == "inlink" ? image + "/" : "")
                        + Normalize((string)declaredLinks[0].WzValue);
                }
                // Preserve origins without flattening duplicate unrelated collision properties.
                canvases.Add(new { image, property = path, width = canvas.PngProperty.Width,
                    height = canvas.PngProperty.Height, format = (int)canvas.PngProperty.Format,
                    origins = props.Where(p => p.Name == "origin").Select(Dump).ToArray(),
                    terminal_inline = target == null });
            }
            if (target != null)
            {
                var parts = target.Split('/');
                var split = Array.FindIndex(parts, p => p.EndsWith(".img", StringComparison.Ordinal));
                if (split < 2 || split == parts.Length - 1)
                    throw new InvalidDataException("Invalid artwork link target");
                var targetImage = string.Join('/', parts.Take(split + 1));
                var targetPath = string.Join('/', parts.Skip(split + 1));
                var prefix = string.Join('/', parts.Take(split));
                var copied = allowed.ContainsKey(prefix);
                if (!copied && !new[] { "Map/Tile/_Canvas", "Map/Obj/_Canvas", "Map/Back/_Canvas" }
                    .Contains(prefix)) throw new InvalidDataException("Out-of-scope artwork link");
                links.Add(new { image, property = path, kind, target, target_is_copied = copied });
                if (copied) queue.Enqueue((targetImage, targetPath, depth + 1));
            }
            if (property is WzUOLProperty or WzCanvasProperty or WzVectorProperty)
                return;
            if (property.WzProperties != null)
                foreach (var child in property.WzProperties)
                    Scan(child, image, path + "/" + child.Name, depth, treeDepth + 1);
        }
        while (queue.Count > 0)
        {
            var item = queue.Dequeue();
            if (item.Depth > 16 || visited.Count > 10000)
                throw new InvalidDataException("Artwork link budget exceeded");
            if (!visited.Add(item.Image + "/" + item.Property)) continue;
            var slash = item.Image.LastIndexOf('/');
            var category = item.Image[..slash];
            if (!allowed.TryGetValue(category, out var archive))
                throw new InvalidDataException("Only copied artwork categories allowed");
            var image = Image(archive, item.Image[(slash + 1)..]);
            branches.Add(new { image = item.Image, property = item.Property });
            Scan(At(image, item.Property), item.Image, item.Property, item.Depth);
        }
        using var handle = new FileStream(output, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(handle, new { schema = 1, map_id = "000000060", branches, links, canvases,
            pixels_decoded = false, native_acceptance = false, input_sent = false });
        return 0;
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 4 && args[0] == "--trace-artwork")
                return TraceArtwork(args[1], args[2], args[3]);
            if (args.Length == 3 && args[0] == "--artwork-indexes")
                return ArtworkIndex.Run(args[1], args[2]);
            if (args.Length != 3 || args[1] != "60")
                throw new InvalidDataException("Expected copied root, map ID 60, new output directory");
            var root = Path.GetFullPath(args[0]);
            var output = Path.GetFullPath(args[2]);
            if (Directory.Exists(output) || File.Exists(output)) throw new IOException("Output exists");
            Directory.CreateDirectory(output);
            foreach (var relative in new[] { "Map/Map/Map0/Map0_000.wz", "Map/Map_000.wz",
                "Map/Map/Map0/_Canvas/_Canvas_000.wz", "Map/_Canvas/_Canvas_000.wz" })
            {
                var source = Path.Combine(root, relative);
                var locale = WzTool.DetectMapleVersion(source, out var version);
                var file = new WzFile(source, version, locale);
                files.Add(relative, file);
                if (file.ParseWzFile() != WzFileParseStatus.Success)
                    throw new InvalidDataException($"Cannot parse {relative}");
                archives.Add(new { archive = relative, locale = locale.ToString(), version,
                    file.Is64BitWzFile });
            }
            var map = Image("Map/Map/Map0/Map0_000.wz", "000000060.img");
            var raw = new[] { "info", "foothold", "ladderRope", "portal", "miniMap" }
                .ToDictionary(name => name, name => Dump(map[name]
                    ?? throw new InvalidDataException($"Missing {name}")));
            var helper = Image("Map/Map_000.wz", "MapHelper.img");
            var marker = At(helper, "minimap/user");
            // Only this map's placement records. Do not resolve artwork or open other maps.
            var renderSections = map.WzProperties.Where(p => p.Name == "back"
                || (p.Name.Length == 1 && p.Name[0] >= '0' && p.Name[0] <= '7'))
                .ToDictionary(p => p.Name, p => Dump(p));
            var result = new { schema = 1, map_id = "000000060", raw,
                render_sections = renderSections,
                scene_entities = new[] { "life", "reactor" }
                    .ToDictionary(name => name, name => Dump(map[name])),
                portal_helper = Dump(helper["portal"]),
                other_section_names = map.WzProperties.Select(p => p.Name).ToArray(),
                marker = Dump(marker), archives,
                minimap_canvas = ExportCanvas("Map/Map/Map0/Map0_000.wz", "000000060.img",
                    "miniMap/canvas", output, "minimap-canvas"),
                player_marker = ExportCanvas("Map/Map_000.wz", "MapHelper.img", "minimap/user",
                    output, "player-marker") };
            File.WriteAllText(Path.Combine(output, "raw.json"), JsonSerializer.Serialize(result));
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
        finally { foreach (var file in files.Values) file.Dispose(); }
    }
}

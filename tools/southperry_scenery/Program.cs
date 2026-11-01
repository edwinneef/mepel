using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using MapleLib.WzLib;
using MapleLib.WzLib.WzProperties;

// GPL-3.0-only. Separate offline diagnostic; no game/runtime integration.
if (args.Length != 3) throw new ArgumentException("Expected copied artwork root, references, new output");
var root = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[2]);
if (Directory.Exists(output) || File.Exists(output)) throw new IOException("Output exists");
using var request = JsonDocument.Parse(File.ReadAllText(args[1]));
if (request.RootElement.GetProperty("map_id").GetString() != "000000060")
    throw new InvalidDataException("Southperry only");
Directory.CreateDirectory(output);
var archives = new Dictionary<string, string> {
    ["Map/Obj"] = "Map/Obj/Obj_000.wz", ["Map/Tile"] = "Map/Tile/Tile_000.wz",
    ["Map/Back"] = "Map/Back/Back_000.wz", ["Map/Obj/_Canvas"] = "Map/Obj/_Canvas/_Canvas_000.wz" };
var files = new Dictionary<string, WzFile>();
var images = new Dictionary<string, WzImage>();
var branches = new List<object>();
var sprites = new Dictionary<string, object>();
var links = new List<object>();
var branchSprites = new Dictionary<string, List<string>>();
long pixelBudget = 0;
int nodeBudget = 0;
string Normalize(string value)
{
    var result = new List<string>();
    foreach (var part in value.Split('/')) {
        if (part == "..") {
            if (result.Count == 0) throw new InvalidDataException("Link escapes image");
            result.RemoveAt(result.Count - 1);
        } else if (part != ".") {
            if (part.Length == 0 || part.Contains('\\') || part.Contains(':'))
                throw new InvalidDataException("Unsafe property path");
            result.Add(part);
        }
    }
    return string.Join('/', result);
}
WzImage Image(string name)
{
    if (images.TryGetValue(name, out var existing)) return existing;
    var split = name.LastIndexOf('/');
    if (split < 0 || !archives.TryGetValue(name[..split], out var archive) || !name.EndsWith(".img"))
        throw new InvalidDataException("Uncopied/out-of-scope target: " + name);
    if (!files.TryGetValue(archive, out var file)) {
        file = new WzFile(Path.Combine(root, archive), 779, WzMapleVersion.BMS);
        files.Add(archive, file);
        if (file.ParseWzFile() != WzFileParseStatus.Success) throw new InvalidDataException(archive);
    }
    var candidates = file.WzDirectory.WzImages.Where(i => i.Name == name[(split + 1)..]).ToArray();
    if (candidates.Length != 1) throw new InvalidDataException("Missing/ambiguous image: " + name);
    var image = candidates[0];
    if (!image.ParseImage()) throw new InvalidDataException("Cannot parse " + name);
    images.Add(name, image);
    return image;
}
(string Image, string Path) Target(string value)
{
    var parts = Normalize(value).Split('/');
    var split = Array.FindIndex(parts, p => p.EndsWith(".img"));
    if (split < 2 || split >= parts.Length - 1) throw new InvalidDataException("Invalid link");
    return (string.Join('/', parts.Take(split + 1)), string.Join('/', parts.Skip(split + 1)));
}
(WzImageProperty Property, string Image, string Path) At(string image, string path, HashSet<string> trail)
{
    var identity = image + "/" + path;
    if (trail.Count > 16 || !trail.Add(identity)) throw new InvalidDataException("UOL cycle/depth");
    var parts = Normalize(path).Split('/');
    WzImageProperty? current = null;
    for (int i = 0; i < parts.Length; i++) {
        current = current == null ? Image(image)[parts[i]] : current[parts[i]];
        if (current == null) throw new InvalidDataException("Missing property: " + identity);
        if (current is WzUOLProperty uol) {
            var parent = string.Join('/', parts.Take(i));
            var next = Normalize((parent.Length > 0 ? parent + "/" : "") + uol.Value
                                 + (i + 1 < parts.Length ? "/" + string.Join('/', parts.Skip(i + 1)) : ""));
            links.Add(new { source = image + "/" + string.Join('/', parts.Take(i + 1)), kind = "uol", target = image + "/" + next });
            return At(image, next, trail);
        }
    }
    return (current!, image, path);
}
(WzCanvasProperty Canvas, string Image, string Path) Terminal(string image, string path, HashSet<string> trail)
{
    var identity = image + "/" + path;
    if (trail.Count > 16 || !trail.Add(identity)) throw new InvalidDataException("Canvas cycle/depth");
    var found = At(image, path, new HashSet<string>());
    if (found.Property is not WzCanvasProperty canvas) throw new InvalidDataException("Link is not canvas");
    var declared = canvas.WzProperties.Where(p => p.Name is "_inlink" or "_outlink").ToArray();
    if (declared.Length > 1) throw new InvalidDataException("Ambiguous canvas link");
    if (declared.Length == 0) return (canvas, found.Image, found.Path);
    var value = (declared[0].Name == "_inlink" ? found.Image + "/" : "") + (string)declared[0].WzValue;
    var target = Target(value);
    links.Add(new { source = found.Image + "/" + found.Path, kind = declared[0].Name, target = target.Image + "/" + target.Path });
    return Terminal(target.Image, target.Path, trail);
}
object? Scalar(WzImageProperty property, string name) => property.WzProperties.FirstOrDefault(p => p.Name == name)?.WzValue;
void Collect(string image, string path, List<string> result, HashSet<string> trail)
{
    var key = image + "/" + path;
    if (++nodeBudget > 10000 || trail.Count > 32 || !trail.Add(key)) throw new InvalidDataException("Property tree cycle/budget");
    var found = At(image, path, new HashSet<string>());
    if (found.Property is WzCanvasProperty original) {
        result.Add(key);
        if (sprites.ContainsKey(key)) return;
        var terminal = Terminal(found.Image, found.Path, new HashSet<string>());
        var png = terminal.Canvas.PngProperty;
        var pixels = (long)png.Width * png.Height;
        pixelBudget += pixels;
        if (pixels < 1 || pixels > 8000000 || pixelBudget > 100000000) throw new InvalidDataException("Pixel budget");
        var filename = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(key))).ToLowerInvariant()[..24];
        using var bitmap = png.GetImage(false);
        bitmap.Save(Path.Combine(output, filename + ".png"), System.Drawing.Imaging.ImageFormat.Png);
        File.WriteAllBytes(Path.Combine(output, filename + ".compressed.bin"), png.GetCompressedBytes(false));
        var origin = original.WzProperties.OfType<WzVectorProperty>().SingleOrDefault(p => p.Name == "origin")
            ?? terminal.Canvas.WzProperties.OfType<WzVectorProperty>().SingleOrDefault(p => p.Name == "origin");
        sprites.Add(key, new { file = filename + ".png", compressed = filename + ".compressed.bin", image, property = path,
            terminal_image = terminal.Image, terminal_property = terminal.Path, width = png.Width, height = png.Height,
            format = (int)png.Format, origin = origin == null ? new[] { 0, 0 } : new[] { origin.X.Value, origin.Y.Value },
            delay = Scalar(original, "delay"), z = Scalar(original, "z"), a0 = Scalar(original, "a0"), a1 = Scalar(original, "a1") });
        return;
    }
    if (found.Property is WzVectorProperty || found.Property.WzProperties == null) return;
    foreach (var child in found.Property.WzProperties)
        Collect(found.Image, found.Path + "/" + child.Name, result, new HashSet<string>(trail));
}
try {
    foreach (var row in request.RootElement.GetProperty("core_scenery").EnumerateArray()) {
        var image = row.GetProperty("image").GetString()!;
        foreach (var entry in row.GetProperty("entries").EnumerateArray()) {
            var path = entry.GetString()!;
            var result = new List<string>();
            Collect(image, path, result, new HashSet<string>());
            if (result.Count == 0) throw new InvalidDataException("No pictures under " + image + "/" + path);
            branchSprites.Add(image + "/" + path, result);
            branches.Add(new { image, property = path, sprites = result });
        }
    }
    File.WriteAllText(Path.Combine(output, "pictures.json"), JsonSerializer.Serialize(new {
        schema = 1, map_id = "000000060", branches, sprites, links, opened_archives = files.Keys,
        parsed_images = images.Keys, pixel_count = pixelBudget, input_sent = false, native_acceptance = false }));
} finally { foreach (var file in files.Values) file.Dispose(); }

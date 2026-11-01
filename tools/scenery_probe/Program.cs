using System.IO;
using System.Text.Json;
using MapleLib.WzLib;
using MapleLib.WzLib.WzProperties;

// GPL-3.0-only. Small copied-artwork probe, independent of the runtime/dirty extractor.
if (args.Length != 2) throw new ArgumentException("Expected copied artwork root and new output folder");
var root = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[1]);
if (Directory.Exists(output)) throw new IOException("Output exists");
Directory.CreateDirectory(output);
var report = new List<object>();
foreach (var item in new[] {
    (Category: "Obj", Image: "obj_housePT.img", Property: "house0/basic/0/0", Name: "house"),
    (Category: "Obj", Image: "obj_housePT.img", Property: "house0/deco/0/0", Name: "house-decoration"),
    (Category: "Tile", Image: "tile_whiteMarble.img", Property: "enH0/0", Name: "platform-edge") })
{
    var archive = $"Map/{item.Category}/{item.Category}_000.wz";
    using var file = new WzFile(Path.Combine(root, archive), 779, WzMapleVersion.BMS);
    if (file.ParseWzFile() != WzFileParseStatus.Success) throw new InvalidDataException(archive);
    // Observed artwork indexes put these records directly in the category root.
    var matches = file.WzDirectory.WzImages.Where(i => i.Name == item.Image).ToArray();
    if (matches.Length != 1) throw new InvalidDataException("Missing/ambiguous artwork image");
    var image = matches[0];
    image.ParseImage();
    WzImageProperty? property = null;
    foreach (var part in item.Property.Split('/'))
    {
        if (property is WzUOLProperty) throw new InvalidDataException("Unexpected UOL");
        property = property == null ? image[part] : property[part];
        if (property == null) throw new InvalidDataException(item.Property);
    }
    if (property is not WzCanvasProperty canvas) throw new InvalidDataException("Expected inline canvas");
    if (canvas.WzProperties.Any(p => p.Name is "_inlink" or "_outlink"))
        throw new InvalidDataException("Probe accepts existing inline pictures only");
    var png = canvas.PngProperty;
    if ((int)png.Format != 1 || (long)png.Width * png.Height > 1000000)
        throw new InvalidDataException("Unsupported image format/size");
    File.WriteAllBytes(Path.Combine(output, item.Name + ".compressed.bin"), png.GetCompressedBytes(false));
    using var bitmap = png.GetImage(false);
    bitmap.Save(Path.Combine(output, item.Name + ".png"), System.Drawing.Imaging.ImageFormat.Png);
    var origin = canvas.WzProperties.OfType<WzVectorProperty>().SingleOrDefault(p => p.Name == "origin");
    report.Add(new { name = item.Name, archive, image = item.Image, property = item.Property,
        width = png.Width, height = png.Height, format = (int)png.Format,
        origin = origin == null ? null : new[] { origin.X.Value, origin.Y.Value } });
}
File.WriteAllText(Path.Combine(output, "assets.json"), JsonSerializer.Serialize(report));

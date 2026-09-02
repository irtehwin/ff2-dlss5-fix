from pathlib import Path
import sys

path = Path(sys.argv[1])
s = path.read_text(encoding="utf-8")

needle = """static bool EnsureSub(SubTex &s, ID3D12Device *dev, const D3D12_RESOURCE_DESC &src,
                      const char *label)
{
    if (s.tex != nullptr && s.width == src.Width && s.height == src.Height &&
        s.fmt == src.Format)
        return true;
"""

replacement = """static bool CodecFormatSupported(ID3D12Device *dev, DXGI_FORMAT fmt)
{
    if (dev == nullptr || fmt == DXGI_FORMAT_UNKNOWN) return false;
    D3D12_FEATURE_DATA_FORMAT_SUPPORT fs = {};
    fs.Format = fmt;
    if (FAILED(dev->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &fs, sizeof(fs))))
        return false;
    return (fs.Support1 & D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE) != 0 &&
           (fs.Support2 & D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE) != 0;
}

static DXGI_FORMAT CodecCompatibleFormat(ID3D12Device *dev, DXGI_FORMAT fmt)
{
    if (CodecFormatSupported(dev, fmt)) return fmt;
    if (fmt == DXGI_FORMAT_R16G16B16A16_TYPELESS &&
        CodecFormatSupported(dev, DXGI_FORMAT_R16G16B16A16_FLOAT))
        return DXGI_FORMAT_R16G16B16A16_FLOAT;
    return DXGI_FORMAT_UNKNOWN;
}

static bool EnsureSub(SubTex &s, ID3D12Device *dev, const D3D12_RESOURCE_DESC &src,
                      const char *label)
{
    const DXGI_FORMAT codec_fmt = CodecCompatibleFormat(dev, src.Format);
    if (codec_fmt == DXGI_FORMAT_UNKNOWN)
    {
        Log("  %s: no codec-compatible typed substitute for fmt=%u", label, src.Format);
        return false;
    }

    if (s.tex != nullptr && s.width == src.Width && s.height == src.Height &&
        s.fmt == codec_fmt)
        return true;
"""

if needle not in s:
    raise SystemExit("EnsureSub anchor not found; upstream changed.")
s = s.replace(needle, replacement, 1)

s = s.replace(
"""    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;                                        // the whole point
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
""",
"""    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;
    d.Format    = codec_fmt;
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
""", 1)

s = s.replace(
"""    s.fmt    = src.Format;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: single-mip substitute ready, %llux%u fmt=%u", label, s.width, s.height, s.fmt);
""",
"""    s.fmt    = codec_fmt;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: substitute ready, %llux%u srcfmt=%u codecfmt=%u%s",
        label, s.width, s.height, src.Format, s.fmt,
        src.Format != s.fmt ? "  <== FF2 typed-format bridge active" : "");
""", 1)

old = """                if (SubOutput() && d.MipLevels > 1 && EnsureSub(g_sub_out, dev, d, "Output"))
                {
"""
new = """                const bool bad_codec_format = !CodecFormatSupported(dev, d.Format);
                const bool needs_output_bridge = d.MipLevels > 1 || bad_codec_format;
                if (SubOutput() && needs_output_bridge &&
                    EnsureSub(g_sub_out, dev, d, "Output"))
                {
                    if (bad_codec_format && (n <= 6 || (n % 3600) == 0))
                        Log("  FF2/output bridge: fmt=%u -> codec fmt=%u",
                            d.Format, g_sub_out.fmt);
"""
if old not in s:
    raise SystemExit("Output-substitution anchor not found; upstream changed.")
s = s.replace(old, new, 1)

path.write_text(s, encoding="utf-8")
print("FF2 patch applied.")

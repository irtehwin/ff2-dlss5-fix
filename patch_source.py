from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_source_v3_unorm.py <dlss5-d3d12-fix.cpp>")

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

    // FF2 diagnostic v3:
    // Test the UNORM sibling of R16G16B16A16_TYPELESS instead of FLOAT.
    if (fmt == DXGI_FORMAT_R16G16B16A16_TYPELESS &&
        CodecFormatSupported(dev, DXGI_FORMAT_R16G16B16A16_UNORM))
        return DXGI_FORMAT_R16G16B16A16_UNORM;

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
    raise SystemExit("ERROR: EnsureSub anchor not found.")
s = s.replace(needle, replacement, 1)

old_desc = """    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;                                        // the whole point
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
"""
new_desc = """    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;
    d.Format    = codec_fmt;
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
"""
if old_desc not in s:
    raise SystemExit("ERROR: resource-desc anchor not found.")
s = s.replace(old_desc, new_desc, 1)

old_finish = """    s.fmt    = src.Format;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: single-mip substitute ready, %llux%u fmt=%u", label, s.width, s.height, s.fmt);
"""
new_finish = """    s.fmt    = codec_fmt;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: substitute ready, %llux%u srcfmt=%u codecfmt=%u%s",
        label, s.width, s.height, src.Format, s.fmt,
        src.Format != s.fmt ? "  <== FF2 v3 UNORM bridge active" : "");
"""
if old_finish not in s:
    raise SystemExit("ERROR: substitute-finish anchor not found.")
s = s.replace(old_finish, new_finish, 1)

old_output = """                if (SubOutput() && d.MipLevels > 1 && EnsureSub(g_sub_out, dev, d, "Output"))
                {
"""
new_output = """                const bool bad_codec_format = !CodecFormatSupported(dev, d.Format);
                const bool needs_output_bridge = d.MipLevels > 1 || bad_codec_format;
                if (SubOutput() && needs_output_bridge &&
                    EnsureSub(g_sub_out, dev, d, "Output"))
                {
                    if (bad_codec_format && (n <= 6 || (n % 3600) == 0))
                        Log("  FF2/v3 output bridge: fmt=%u -> codec fmt=%u",
                            d.Format, g_sub_out.fmt);
"""
if old_output not in s:
    raise SystemExit("ERROR: output substitution anchor not found.")
s = s.replace(old_output, new_output, 1)

old_gate = """    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr || !IsDetoured(eval)) return;
"""
new_gate = """    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr) return;
    if (GetModuleHandleW(L"nvngx_dlssnr.dll") == nullptr) return;
"""
if old_gate not in s:
    raise SystemExit("ERROR: NGX readiness-gate anchor not found.")
s = s.replace(old_gate, new_gate, 1)

old_log = """    Log("Entry point is already detoured by another add-on. Installing "
        "downstream of it.");
"""
new_log = """    Log("FF2/RenoDX v4.7 mode: NR runtime loaded; installing outer NGX "
        "export hook for UNORM format test.");
"""
if old_log not in s:
    raise SystemExit("ERROR: hook-install log anchor not found.")
s = s.replace(old_log, new_log, 1)

s = s.replace('#define PROBE_VERSION "2.6.1"',
              '#define PROBE_VERSION "2.6.1-ff2.3-unorm"', 1)

path.write_text(s, encoding="utf-8")
print("FF2 v3 UNORM diagnostic patch applied.")

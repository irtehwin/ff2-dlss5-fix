from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_source_v5.py <dlss5-d3d12-fix.cpp>')

path = Path(sys.argv[1])
s = path.read_text(encoding='utf-8')

# --- FF2 FLOAT bridge (known-good format choice) ---
old = '''static bool EnsureSub(SubTex &s, ID3D12Device *dev, const D3D12_RESOURCE_DESC &src,
                      const char *label)
{
    if (s.tex != nullptr && s.width == src.Width && s.height == src.Height &&
        s.fmt == src.Format)
        return true;
'''
new = '''static bool CodecFormatSupported(ID3D12Device *dev, DXGI_FORMAT fmt)
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
'''
if old not in s: raise SystemExit('ERROR: EnsureSub anchor not found')
s = s.replace(old, new, 1)

old = '''    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;                                        // the whole point
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
'''
new = '''    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;
    d.Format    = codec_fmt;
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
'''
if old not in s: raise SystemExit('ERROR: resource desc anchor not found')
s = s.replace(old, new, 1)

old = '''    s.fmt    = src.Format;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: single-mip substitute ready, %llux%u fmt=%u", label, s.width, s.height, s.fmt);
'''
new = '''    s.fmt    = codec_fmt;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: substitute ready, %llux%u srcfmt=%u codecfmt=%u%s",
        label, s.width, s.height, src.Format, s.fmt,
        src.Format != s.fmt ? "  <== FF2 FLOAT bridge active" : "");
'''
if old not in s: raise SystemExit('ERROR: substitute finish anchor not found')
s = s.replace(old, new, 1)

old = '''                if (SubOutput() && d.MipLevels > 1 && EnsureSub(g_sub_out, dev, d, "Output"))
                {
'''
new = '''                const bool bad_codec_format = !CodecFormatSupported(dev, d.Format);
                const bool needs_output_bridge = d.MipLevels > 1 || bad_codec_format;
                if (SubOutput() && needs_output_bridge &&
                    EnsureSub(g_sub_out, dev, d, "Output"))
                {
                    if (bad_codec_format && (n <= 6 || (n % 3600) == 0))
                        Log("  FF2/v5 output bridge: fmt=%u -> codec fmt=%u",
                            d.Format, g_sub_out.fmt);
'''
if old not in s: raise SystemExit('ERROR: output substitution anchor not found')
s = s.replace(old, new, 1)

# --- RenoDX v4.7 readiness fix ---
old = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr || !IsDetoured(eval)) return;
'''
new = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr) return;
    if (GetModuleHandleW(L"nvngx_dlssnr.dll") == nullptr) return;
'''
if old not in s: raise SystemExit('ERROR: readiness anchor not found')
s = s.replace(old, new, 1)

old = '''    Log("Entry point is already detoured by another add-on. Installing "
        "downstream of it.");
'''
new = '''    Log("FF2/RenoDX v4.7 mode: NR runtime loaded; installing outer NGX "
        "hook for FLOAT bridge + forced-reset diagnostic.");
'''
if old not in s: raise SystemExit('ERROR: hook log anchor not found')
s = s.replace(old, new, 1)

# --- v5 diagnostic: force Reset=1 for each DLSS/RR evaluate while RenoDX sees it ---
old = '''    ID3D12Resource *orig_out = nullptr;
    ID3D12Resource *orig_dep = nullptr;
    bool did_out = false, did_dep = false;
    auto *list = static_cast<ID3D12GraphicsCommandList *>(cmdlist);
    auto *par  = const_cast<NVSDK_NGX_Parameter *>(p);
'''
new = '''    ID3D12Resource *orig_out = nullptr;
    ID3D12Resource *orig_dep = nullptr;
    bool did_out = false, did_dep = false;
    auto *list = static_cast<ID3D12GraphicsCommandList *>(cmdlist);
    auto *par  = const_cast<NVSDK_NGX_Parameter *>(p);

    int original_reset = 0;
    bool restore_reset = false;
'''
if old not in s: raise SystemExit('ERROR: evaluate locals anchor not found')
s = s.replace(old, new, 1)

old = '''    const bool allowed = ShouldSubstitute(handle);
    if (n <= 6 || (n % 3600) == 0)
        Log("  evaluate handle=%p feature id=%d, substitution %s", handle,
            FeatureIdOf(handle), allowed ? "allowed" : "skipped");
'''
new = '''    const bool allowed = ShouldSubstitute(handle);

    // Diagnostic only: force a temporal reset on the host DLSS evaluate.
    // RenoDX derives its inline feature-18 pass from this parameter block, so
    // this tests whether accumulated NR history is the source of the green grain.
    if (allowed && par != nullptr && par->Get("Reset", &original_reset) == NGX_SUCCESS)
    {
        par->Set("Reset", 1);
        restore_reset = true;
        if (n <= 6 || (n % 600) == 0)
            Log("  FF2/v5 forced Reset=1 (original=%d) for temporal-history test", original_reset);
    }

    if (n <= 6 || (n % 3600) == 0)
        Log("  evaluate handle=%p feature id=%d, substitution %s", handle,
            FeatureIdOf(handle), allowed ? "allowed" : "skipped");
'''
if old not in s: raise SystemExit('ERROR: allowed anchor not found')
s = s.replace(old, new, 1)

old = '''    // Always hand the block back exactly as it was found.
    if (did_out) par->Set("Output", orig_out);
    if (did_dep) par->Set("Depth", orig_dep);

    LeaveCriticalSection(&g_state_cs);
'''
new = '''    // Always hand the block back exactly as it was found.
    if (did_out) par->Set("Output", orig_out);
    if (did_dep) par->Set("Depth", orig_dep);
    if (restore_reset) par->Set("Reset", original_reset);

    LeaveCriticalSection(&g_state_cs);
'''
if old not in s: raise SystemExit('ERROR: restore anchor not found')
s = s.replace(old, new, 1)

s = s.replace('#define PROBE_VERSION "2.6.1"',
              '#define PROBE_VERSION "2.6.1-ff2.5-reset"', 1)

path.write_text(s, encoding='utf-8')
print('FF2 v5 applied: FLOAT bridge + RenoDX hook fix + forced Reset=1 diagnostic.')

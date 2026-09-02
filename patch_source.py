from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_source_v6.py <dlss5-d3d12-fix.cpp>")

path = Path(sys.argv[1])
s = path.read_text(encoding="utf-8")

def repl(old, new, name):
    global s
    if old not in s:
        raise SystemExit(f"ERROR: {name} anchor not found")
    s = s.replace(old, new, 1)

repl('#define PROBE_VERSION "2.6.1"',
     '#define PROBE_VERSION "2.6.1-ff2.6-clear-reset"', "version")

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
repl(old, new, "EnsureSub")

old = '''    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;                                        // the whole point
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    d.Layout    = D3D12_TEXTURE_LAYOUT_UNKNOWN;
'''
new = '''    D3D12_RESOURCE_DESC d = src;
    d.MipLevels = 1;
    d.Format    = codec_fmt;
    d.Flags     = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    if (_stricmp(label, "Output") == 0)
        d.Flags |= D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    d.Layout    = D3D12_TEXTURE_LAYOUT_UNKNOWN;
'''
repl(old, new, "resource desc")

old = '''    s.width  = src.Width;
    s.height = src.Height;
    s.fmt    = src.Format;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: single-mip substitute ready, %llux%u fmt=%u", label, s.width, s.height, s.fmt);
    return true;
}
'''
new = '''    s.width  = src.Width;
    s.height = src.Height;
    s.fmt    = codec_fmt;
    s.state  = D3D12_RESOURCE_STATE_COMMON;
    Log("  %s: substitute ready, %llux%u srcfmt=%u codecfmt=%u%s",
        label, s.width, s.height, src.Format, s.fmt,
        src.Format != s.fmt ? "  <== FF2 FLOAT bridge active" : "");
    return true;
}
'''
repl(old, new, "EnsureSub finish")

old = '''static SubTex g_sub_out;
static SubTex g_sub_depth;
static int    g_fix = -1;
'''
new = '''static SubTex g_sub_out;
static SubTex g_sub_depth;
static int    g_fix = -1;

static ID3D12DescriptorHeap *g_ff2_clear_rtv_heap = nullptr;
static D3D12_CPU_DESCRIPTOR_HANDLE g_ff2_clear_rtv = {};
static ID3D12Resource *g_ff2_clear_rtv_resource = nullptr;

static bool EnsureClearRTV(ID3D12Device *dev, ID3D12Resource *res)
{
    if (dev == nullptr || res == nullptr) return false;
    if (g_ff2_clear_rtv_heap != nullptr && g_ff2_clear_rtv_resource == res)
        return true;

    D3D12_DESCRIPTOR_HEAP_DESC hd = {};
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    hd.NumDescriptors = 1;

    ID3D12DescriptorHeap *heap = nullptr;
    if (FAILED(dev->CreateDescriptorHeap(&hd, __uuidof(ID3D12DescriptorHeap),
                                         reinterpret_cast<void **>(&heap))) ||
        heap == nullptr)
        return false;

    D3D12_RENDER_TARGET_VIEW_DESC vd = {};
    vd.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    vd.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
    vd.Texture2D.MipSlice = 0;
    vd.Texture2D.PlaneSlice = 0;

    const D3D12_CPU_DESCRIPTOR_HANDLE h = heap->GetCPUDescriptorHandleForHeapStart();
    dev->CreateRenderTargetView(res, &vd, h);

    // This diagnostic keeps old one-descriptor heaps alive for process lifetime.
    // They are tiny, and this avoids releasing descriptor storage before GPU work completes.
    g_ff2_clear_rtv_heap = heap;
    g_ff2_clear_rtv = h;
    g_ff2_clear_rtv_resource = res;
    Log("  FF2/v6 clear RTV ready for FLOAT substitute");
    return true;
}
'''
repl(old, new, "SubTex globals")

old = '''                if (SubOutput() && d.MipLevels > 1 && EnsureSub(g_sub_out, dev, d, "Output"))
                {
'''
new = '''                const bool bad_codec_format = !CodecFormatSupported(dev, d.Format);
                const bool needs_output_bridge = d.MipLevels > 1 || bad_codec_format;
                if (SubOutput() && needs_output_bridge &&
                    EnsureSub(g_sub_out, dev, d, "Output"))
                {
                    if (bad_codec_format && (n <= 6 || (n % 600) == 0))
                        Log("  FF2/v6 output bridge: fmt=%u -> codec fmt=%u",
                            d.Format, g_sub_out.fmt);
'''
repl(old, new, "output substitution")

# Insert the clear between the end of the existing PreloadOutput block and the
# stable "NGX writes the output through a UAV" comment. This deliberately avoids
# exact-matching the whole upstream block, which has changed comments/spacing.
preload_pos = s.find("                    if (PreloadOutput())")
if preload_pos < 0:
    raise SystemExit("ERROR: PreloadOutput block not found")

uav_comment = """                    // NGX writes the output through a UAV, so hand it over in
                    // that state exactly as the game would have.
"""
comment_pos = s.find(uav_comment, preload_pos)
if comment_pos < 0:
    raise SystemExit("ERROR: output UAV comment not found after PreloadOutput block")

clear_code = """                    else if (g_sub_out.fmt == DXGI_FORMAT_R16G16B16A16_FLOAT &&
                             EnsureClearRTV(dev, g_sub_out.tex))
                    {
                        ToState(list, g_sub_out, D3D12_RESOURCE_STATE_RENDER_TARGET);
                        const FLOAT clear_rgba[4] = { 0.0f, 0.0f, 0.0f, 1.0f };
                        list->ClearRenderTargetView(g_ff2_clear_rtv, clear_rgba, 0, nullptr);
                        if (n <= 6 || (n % 600) == 0)
                            Log("  FF2/v6 cleared substitute to finite black alpha=1 before DLSS");
                    }
"""

# The comment immediately follows the closing brace of the existing if block,
# so inserting here forms a valid if (...) { ... } else if (...) { ... } chain.
s = s[:comment_pos] + clear_code + s[comment_pos:]

old = '''    auto *list = static_cast<ID3D12GraphicsCommandList *>(cmdlist);
    auto *par  = const_cast<NVSDK_NGX_Parameter *>(p);

    // Deliberately NOT held across the forwarded call.
'''
new = '''    auto *list = static_cast<ID3D12GraphicsCommandList *>(cmdlist);
    auto *par  = const_cast<NVSDK_NGX_Parameter *>(p);

    int original_reset = 0;
    bool forced_reset = false;
    if (par != nullptr && ShouldSubstitute(handle) &&
        par->Get("Reset", &original_reset) == NGX_SUCCESS)
    {
        par->Set("Reset", 1);
        forced_reset = true;
        if (n <= 6 || (n % 600) == 0)
            Log("  FF2/v6 forced Reset=1 (original=%d)", original_reset);
    }

    // Deliberately NOT held across the forwarded call.
'''
repl(old, new, "reset insertion")

old = '''    HookRestore(g_hook);
    LeaveCriticalSection(&g_hook_cs);

    EnterCriticalSection(&g_state_cs);
'''
new = '''    HookRestore(g_hook);
    LeaveCriticalSection(&g_hook_cs);

    if (forced_reset)
        par->Set("Reset", original_reset);

    EnterCriticalSection(&g_state_cs);
'''
repl(old, new, "reset restore")

old = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr || !IsDetoured(eval)) return;
'''
new = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr) return;
    if (GetModuleHandleW(L"nvngx_dlssnr.dll") == nullptr) return;
'''
repl(old, new, "RenoDX readiness")

old = '''    Log("Entry point is already detoured by another add-on. Installing "
        "downstream of it.");
'''
new = '''    Log("FF2/RenoDX v4.7 mode: NR runtime loaded; installing outer NGX hook "
        "for FLOAT bridge + reset + clean-output diagnostic.");
'''
repl(old, new, "install log")

path.write_text(s, encoding="utf-8")
print("FF2 v6 applied: FLOAT bridge + Reset=1 + zero/alpha1 output-clear diagnostic.")

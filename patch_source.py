from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_source_v4.py <dlss5-d3d12-fix.cpp>')

path = Path(sys.argv[1])
s = path.read_text(encoding='utf-8')

# ReShade SDK header for resource-view diagnostics
anchor = '#include <cstdint>\n'
if anchor not in s:
    raise SystemExit('ERROR: include anchor not found')
s = s.replace(anchor, anchor + '#include <reshade.hpp>\n', 1)

# Working FF2 FLOAT bridge
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
if old not in s:
    raise SystemExit('ERROR: EnsureSub anchor not found')
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
if old not in s:
    raise SystemExit('ERROR: resource-desc anchor not found')
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
if old not in s:
    raise SystemExit('ERROR: substitute-finish anchor not found')
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
                        Log("  FF2/v4 output bridge: fmt=%u -> codec fmt=%u",
                            d.Format, g_sub_out.fmt);
'''
if old not in s:
    raise SystemExit('ERROR: output substitution anchor not found')
s = s.replace(old, new, 1)

# RenoDX v4.7 readiness fix
old = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr || !IsDetoured(eval)) return;
'''
new = '''    void *eval = reinterpret_cast<void *>(
        GetProcAddress(ngx, "NVSDK_NGX_D3D12_EvaluateFeature"));
    if (eval == nullptr) return;
    if (GetModuleHandleW(L"nvngx_dlssnr.dll") == nullptr) return;
'''
if old not in s:
    raise SystemExit('ERROR: NGX readiness anchor not found')
s = s.replace(old, new, 1)

old = '''    Log("Entry point is already detoured by another add-on. Installing "
        "downstream of it.");
'''
new = '''    Log("FF2/RenoDX v4.7 mode: NR runtime loaded; installing outer NGX "
        "export hook for FLOAT bridge + view diagnostics.");
'''
if old not in s:
    raise SystemExit('ERROR: hook log anchor not found')
s = s.replace(old, new, 1)

# Resource-view diagnostic callback
insert_anchor = '''// ---------------------------------------------------------------------------
// Inline hook
'''
diag = r'''// ---------------------------------------------------------------------------
// FF2 v4 resource-view diagnostics
// ---------------------------------------------------------------------------
static const char *ViewUsageName(reshade::api::resource_usage u)
{
    using U = reshade::api::resource_usage;
    if (u == U::unordered_access) return "UAV";
    if (u == U::render_target) return "RTV";
    if (u == U::depth_stencil || u == U::depth_stencil_read || u == U::depth_stencil_write) return "DSV";
    if (u == U::shader_resource || u == U::shader_resource_pixel || u == U::shader_resource_non_pixel) return "SRV";
    return "OTHER";
}

static void OnInitResourceView(
    reshade::api::device *device,
    reshade::api::resource resource,
    reshade::api::resource_usage usage,
    const reshade::api::resource_view_desc &vd,
    reshade::api::resource_view view)
{
    if (device == nullptr || device->get_api() != reshade::api::device_api::d3d12 || resource.handle == 0)
        return;

    auto *res = reinterpret_cast<ID3D12Resource *>(static_cast<uintptr_t>(resource.handle));
    D3D12_RESOURCE_DESC rd = {};
    __try { rd = res->GetDesc(); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return; }

    if (rd.Format != DXGI_FORMAT_R16G16B16A16_TYPELESS &&
        rd.Format != DXGI_FORMAT_R32G8X24_TYPELESS &&
        rd.Format != DXGI_FORMAT_R16G16_TYPELESS)
        return;

    Log("[VIEW] resource=%p basefmt=%u %llux%u usage=%s(0x%X) viewfmt=%u type=%u mip=%u levels=%u layer=%u layers=%u descriptor=0x%llX",
        static_cast<void *>(res), static_cast<unsigned>(rd.Format),
        static_cast<unsigned long long>(rd.Width), rd.Height,
        ViewUsageName(usage), static_cast<unsigned>(usage),
        static_cast<unsigned>(vd.format), static_cast<unsigned>(vd.type),
        vd.texture.first_level, vd.texture.levels,
        vd.texture.first_layer, vd.texture.layers,
        static_cast<unsigned long long>(view.handle));
}

'''
if insert_anchor not in s:
    raise SystemExit('ERROR: diagnostic insertion anchor not found')
s = s.replace(insert_anchor, diag + insert_anchor, 1)

old = '''        if (!RegisterWithReShade(module)) return FALSE;

        FILE *f = nullptr;
'''
new = '''        if (!RegisterWithReShade(module)) return FALSE;
        reshade::register_event<reshade::addon_event::init_resource_view>(&OnInitResourceView);

        FILE *f = nullptr;
'''
if old not in s:
    raise SystemExit('ERROR: registration anchor not found')
s = s.replace(old, new, 1)

old = '''        ReportOutcome();
        if (g_unregister != nullptr) g_unregister(g_self);
'''
new = '''        ReportOutcome();
        reshade::unregister_event<reshade::addon_event::init_resource_view>(&OnInitResourceView);
        if (g_unregister != nullptr) g_unregister(g_self);
'''
if old not in s:
    raise SystemExit('ERROR: unregister anchor not found')
s = s.replace(old, new, 1)

s = s.replace('#define PROBE_VERSION "2.6.1"',
              '#define PROBE_VERSION "2.6.1-ff2.4-viewdiag"', 1)

path.write_text(s, encoding='utf-8')
print('FF2 v4 diagnostic patch applied.')

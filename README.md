# FF2 DLSS5 GitHub Actions builder

Upload all files from this ZIP to a new GitHub repository, including `.github`.

Then open **Actions** -> **Build FF2 DLSS5 format bridge** -> **Run workflow**.

When the run finishes, download the artifact named **FF2-DLSS5-format9-test**.

The workflow clones the open-source NIGos D3D12 helper, patches its output
substitution so Fatal Frame II's DXGI format 9 (`R16G16B16A16_TYPELESS`) can be
bridged through format 10 (`R16G16B16A16_FLOAT`), then compiles it with MSVC on
GitHub's Windows runner.

This is experimental. If the game hangs or the driver resets, remove the test
add-on and inspect the logs instead of repeatedly relaunching.

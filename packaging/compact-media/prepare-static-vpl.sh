#!/usr/bin/env bash
# Keep Intel QSV in the standalone runtime. The C-only configure probe has to
# link the C++ VPL dispatcher and its transitive system libraries statically.
set -euo pipefail
evidence="$1"
mkdir -p "$evidence"
exec > >(tee "$evidence/static-vpl.log") 2>&1
export PKG_CONFIG_PATH="$MINGW_PREFIX/lib/pkgconfig:$MINGW_PREFIX/share/pkgconfig"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"
echo "Toolchain: $MSYSTEM $MINGW_PREFIX"
command -v gcc pkgconf
gcc --version
pkgconf --modversion vpl
pkgconf --atleast-version=2.6 vpl
pc="$MINGW_PREFIX/lib/pkgconfig/vpl.pc"
test -f "$MINGW_PREFIX/lib/libvpl.a"
cp "$pc" "$evidence/vpl-original.pc"
# Preserve any declared private dependencies; augment only this build runner's
# metadata. Do not alter FFmpeg's configure checks or disable hardware support.
private="-lstdc++ -lwinpthread -lsetupapi -lcfgmgr32 -ladvapi32 -lshlwapi -lversion -lole32 -loleaut32 -luuid -ldxgi -ld3d11"
if grep -q '^Libs.private:' "$pc"; then
    sed -i "/^Libs.private:/s|$| $private|" "$pc"
else
    printf '\nLibs.private: %s\n' "$private" >> "$pc"
fi
cp "$pc" "$evidence/vpl-static.pc"
cat "$pc"
pkgconf --static --cflags --libs vpl
cat > "$evidence/vpl-link.c" <<'EOF'
#include <mfxvideo.h>
#include <mfxdispatcher.h>
int main(void) {
    mfxLoader loader = MFXLoad();
    if (loader) MFXUnload(loader);
    return 0;
}
EOF
# Use precisely the same C driver, static flags and metadata as configure.
gcc -static $(pkgconf --cflags vpl) "$evidence/vpl-link.c" \
    $(pkgconf --static --libs vpl) -o "$evidence/vpl-link.exe"
objdump -p "$evidence/vpl-link.exe" > "$evidence/vpl-link-imports.txt"
if grep -Ei 'DLL Name:.*(libvpl|libstdc\+\+|libgcc|libwinpthread|msys-2\.0)' "$evidence/vpl-link-imports.txt"; then
    echo "Unexpected non-system runtime dependency in static dispatcher"
    exit 1
fi
"$evidence/vpl-link.exe"
echo "Static Intel VPL C link and standalone loader passed (GPU not tested)."

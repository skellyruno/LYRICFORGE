#!/usr/bin/env bash
# Experimental candidate: one FFmpeg 8.1.3 shared media stack for CLI and PyAV.
set -euo pipefail
base="$(pwd)/shared-candidate"
vendor="$base/vendor"
evidence="$base/build-evidence"
mkdir -p "$vendor" "$evidence"
export PKG_CONFIG_PATH="$MINGW_PREFIX/lib/pkgconfig:$MINGW_PREFIX/share/pkgconfig"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"
export LC_ALL=C
git clone --depth 1 --branch n8.1.3 https://github.com/FFmpeg/FFmpeg.git "$base/ffmpeg"
cd "$base/ffmpeg"
test "$(git rev-parse HEAD)" = '1041abdc962f4cc4f394aa8de9dc5236c0c3b9e7'
trap 'code=$?; if [ -f ffbuild/config.log ]; then cp ffbuild/config.log "$evidence/ffmpeg-config.log"; fi; exit $code' EXIT
pacman -Q > "$evidence/msys2-packages.txt"
# Preserve native decoding, muxing, demuxing, filtering and encoding.
./configure \
  --prefix="$vendor" --arch=x86_64 --target-os=mingw32 \
  --pkg-config=pkgconf --enable-shared --disable-static \
  --enable-gpl --enable-version3 --disable-debug --disable-doc \
  --disable-ffplay --disable-autodetect --disable-network \
  --enable-zlib --enable-iconv --enable-libx264 --enable-libass \
  --enable-libvpx --enable-libdav1d --enable-libopus --enable-libvorbis \
  --enable-libmp3lame \
  --enable-ffnvcodec --enable-nvenc --enable-amf --enable-libvpl \
  --enable-d3d11va --enable-dxva2 \
  --disable-indevs --disable-outdevs --enable-indev=lavfi
make -j"$(nproc)"
make install
# FFmpeg's MinGW build produces COFF import libraries for MSVC.
for name in avcodec avdevice avfilter avformat avutil swresample swscale; do
  if [ -f "$vendor/bin/$name.lib" ]; then mv "$vendor/bin/$name.lib" "$vendor/lib/$name.lib"; fi
  test -f "$vendor/lib/$name.lib"
done
# Copy only the recursive native DLL import closure, not MSYS2 itself.
system32="$(cygpath -u "$SYSTEMROOT")/System32"
declare -A scanned
shopt -s nullglob
queue=("$vendor"/bin/*.dll "$vendor/bin/ffmpeg.exe" "$vendor/bin/ffprobe.exe")
for ((i=0;i<${#queue[@]};i++)); do
  file="${queue[i]}"
  name="${file##*/}"
  key="${name,,}"
  if [[ -n "${scanned[$key]+yes}" ]]; then continue; fi
  scanned[$key]=1
  objdump -p "$file" > "$evidence/$name.imports.txt"
  while IFS= read -r dll; do
    dll="${dll%$'\r'}"
    lower="${dll,,}"
    if [[ "$lower" = msys-2.0.dll ]]; then echo "Unexpected MSYS runtime" >&2; exit 1; fi
    if [[ -f "$vendor/bin/$dll" ]]; then queue+=("$vendor/bin/$dll")
    elif [[ "$lower" = api-ms-win-* || "$lower" = ext-ms-win-* || -f "$system32/$dll" ]]; then continue
    elif [[ -f "$MINGW_PREFIX/bin/$dll" ]]; then
      cp "$MINGW_PREFIX/bin/$dll" "$vendor/bin/$dll"
      queue+=("$vendor/bin/$dll")
    else echo "Missing native dependency $dll imported by $name" >&2; exit 1
    fi
  done < <(awk '/DLL Name:/ {print $3}' "$evidence/$name.imports.txt")
done
strip --strip-unneeded "$vendor"/bin/*.dll "$vendor/bin/ffmpeg.exe" "$vendor/bin/ffprobe.exe"
(cd "$vendor/bin"; sha256sum *.dll ffmpeg.exe ffprobe.exe) > "$evidence/native-sha256.txt"
"$vendor/bin/ffmpeg.exe" -hide_banner -buildconf > "$evidence/buildconf.txt" 2>&1
git rev-parse HEAD > "$evidence/ffmpeg-revision.txt"
git archive --format=tar.gz --prefix=ffmpeg/ HEAD > "$base/ffmpeg-source.tar.gz"
cp COPYING* LICENSE* "$evidence/" || true
du -ch "$vendor"/bin/*.dll "$vendor/bin/ffmpeg.exe" | tail -1

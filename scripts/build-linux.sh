#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" ]]; then
  echo "The Linux release image currently supports x86_64 only: $architecture" >&2
  exit 1
fi
build_venv="$(mktemp -d -t pdo-build-venv.XXXXXX)"
app_dir="$project_root/build/PDO.AppDir"
appimage_tool="${APPIMAGETOOL:-$(command -v appimagetool || true)}"

cleanup() {
  rm -rf -- "$build_venv"
}
trap cleanup EXIT

python3 -m venv "$build_venv"
build_python="$build_venv/bin/python"
"$build_python" -m pip install --upgrade pip
cd "$project_root"
"$build_python" -m pip install -r requirements-build.txt

QT_QPA_PLATFORM=offscreen "$build_python" -m pytest \
  tests/test_desktop.py tests/test_linux_tray.py tests/test_integration.py \
  tests/test_importer.py tests/test_exporter.py -q

appstreamcli validate --no-net \
  "$project_root/packaging/linux/io.github.PaDreyer.pdo.appdata.xml"
desktop-file-validate \
  "$project_root/packaging/linux/io.github.PaDreyer.pdo.desktop"

mkdir -p "$project_root/build/spec" "$project_root/dist"
"$build_python" -m PyInstaller \
  --noconfirm --clean --onedir --windowed \
  --name PDO \
  --specpath "$project_root/build/spec" \
  --paths "$project_root/src" \
  --collect-data pdo.desktop \
  --collect-all dbus_next \
  --hidden-import google.genai \
  --hidden-import zhipuai \
  --hidden-import openai \
  "$project_root/src/pdo/desktop/app.py"

QT_QPA_PLATFORM=offscreen "$project_root/dist/PDO/PDO" --smoke-test
cp "$project_root/LICENSE" "$project_root/dist/PDO/LICENSE"

rm -rf -- "$app_dir"
mkdir -p "$app_dir/usr/lib/pdo" "$app_dir/usr/bin" \
  "$app_dir/usr/share/applications" "$app_dir/usr/share/metainfo"
cp -a "$project_root/dist/PDO/." "$app_dir/usr/lib/pdo/"
cp "$project_root/packaging/linux/AppRun" "$app_dir/AppRun"
cp "$project_root/packaging/linux/io.github.PaDreyer.pdo.desktop" \
  "$app_dir/io.github.PaDreyer.pdo.desktop"
cp "$project_root/packaging/linux/io.github.PaDreyer.pdo.desktop" \
  "$app_dir/usr/share/applications/io.github.PaDreyer.pdo.desktop"
cp "$project_root/packaging/linux/io.github.PaDreyer.pdo.appdata.xml" \
  "$app_dir/usr/share/metainfo/io.github.PaDreyer.pdo.appdata.xml"
cp "$project_root/docs/logo.png" "$app_dir/pdo.png"
ln -s ../lib/pdo/PDO "$app_dir/usr/bin/pdo-desktop"
ln -s pdo.png "$app_dir/.DirIcon"
chmod +x "$app_dir/AppRun"

if [[ -z "$appimage_tool" ]]; then
  echo "AppDir created: $app_dir" >&2
  echo "Install appimagetool or set APPIMAGETOOL to build the AppImage." >&2
  exit 2
fi

version="$("$build_python" -c 'import pdo; print(pdo.__version__)')"
deb_arch="amd64"
ARCH="$architecture" "$appimage_tool" \
  "$app_dir" "$project_root/dist/PDO-$version-$architecture.AppImage"

deb_dir="$project_root/build/deb/pdo"
rm -rf -- "$deb_dir"
mkdir -p "$deb_dir/DEBIAN" "$deb_dir/opt/pdo" "$deb_dir/usr/bin" \
  "$deb_dir/usr/share/applications" "$deb_dir/usr/share/icons/hicolor/640x640/apps" \
  "$deb_dir/usr/share/metainfo"
cp -a "$project_root/dist/PDO/." "$deb_dir/opt/pdo/"
cp "$project_root/packaging/linux/io.github.PaDreyer.pdo.desktop" \
  "$deb_dir/usr/share/applications/io.github.PaDreyer.pdo.desktop"
cp "$project_root/packaging/linux/io.github.PaDreyer.pdo.appdata.xml" \
  "$deb_dir/usr/share/metainfo/io.github.PaDreyer.pdo.appdata.xml"
cp "$project_root/docs/logo.png" \
  "$deb_dir/usr/share/icons/hicolor/640x640/apps/pdo.png"
cat > "$deb_dir/usr/bin/pdo-desktop" <<'EOF'
#!/bin/sh
exec /opt/pdo/PDO "$@"
EOF
chmod +x "$deb_dir/usr/bin/pdo-desktop"
cat > "$deb_dir/DEBIAN/control" <<EOF
Package: pdo
Version: $version
Section: utils
Priority: optional
Architecture: $deb_arch
Maintainer: PDO contributors <noreply@github.com>
Depends: libc6 (>= 2.36), libdbus-1-3, libglib2.0-0, libgtk-3-0, libx11-6, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libxkbcommon-x11-0, libgl1, libegl1
Description: Product Description Optimizer desktop application
 Import product data from CSV, improve descriptions, and export results.
EOF
dpkg-deb --build --root-owner-group "$deb_dir" \
  "$project_root/dist/PDO-$version-$deb_arch.deb"

echo "Done: $project_root/dist/PDO-$version-$architecture.AppImage"
echo "Done: $project_root/dist/PDO-$version-$deb_arch.deb"

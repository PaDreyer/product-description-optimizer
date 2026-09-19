FROM python:3.12-bookworm

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        appstream \
        build-essential \
        ca-certificates \
        curl \
        desktop-file-utils \
        file \
        libdbus-1-3 \
        libegl1 \
        libgl1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libx11-6 \
        libxcb-cursor0 \
        libxcb-icccm4 \
        libxcb-keysyms1 \
        libxcb-shape0 \
        libxcb-xinerama0 \
        libxkbcommon-x11-0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 3 \
        --output /tmp/appimagetool.AppImage \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
    && chmod +x /tmp/appimagetool.AppImage \
    && cd /opt \
    && /tmp/appimagetool.AppImage --appimage-extract >/dev/null \
    && mv /opt/squashfs-root /opt/appimagetool \
    && ln -s /opt/appimagetool/AppRun /usr/local/bin/appimagetool \
    && rm /tmp/appimagetool.AppImage

WORKDIR /workspace
ENV APPIMAGETOOL=/usr/local/bin/appimagetool

CMD ["./scripts/build-linux.sh"]

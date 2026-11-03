[app]
title = Wall Climbers
package.name = wallclimbers
package.domain = org.wallclimbers
source.dir = .
source.include_exts = py
version = 1.0

# Если сборка падает на pygame/Cython — закрепи версии, как в заметке к этому файлу:
#   requirements = python3==3.11.15,cython==0.29.34,pygame==2.6.1
requirements = python3,pygame

orientation = portrait
fullscreen = 1
android.archs = arm64-v8a
android.accept_sdk_license = True
# Игре не нужен интернет и другие разрешения
android.permissions =

[buildozer]
log_level = 2
warn_on_root = 1

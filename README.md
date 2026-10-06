# monitor-brightness-ubuntu

Change the brightness of each monitor separately on Ubuntu, like the core feature of [Lunar](https://lunar.fyi) on macOS. It runs as a tray icon: click it, drag a slider per monitor.

- **External monitors:** real brightness over DDC/CI (via `ddcutil`).
- **Laptop screen:** `/sys/class/backlight` (through logind, no root needed).
- **Monitors without DDC:** software dimming with `xrandr`, **X11 sessions only**. GNOME on Wayland would need a Shell extension for this, which isn't written yet, so on Wayland such monitors get no slider.

Scope is brightness only: no contrast, volume, input switching or automatic modes.

Tried so far on one Ubuntu GNOME (Wayland) laptop with its built-in screen and one LG DDC monitor. Everything else, including X11 and software dimming, is covered by unit tests only.

## Install

1. Packages and the I²C kernel module (needed once for DDC):

   ```sh
   sudo apt install git ddcutil python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
   sudo modprobe i2c-dev
   echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf
   sudo groupadd --system i2c 2>/dev/null; sudo usermod -aG i2c $USER
   ```

2. Get the code and install the launcher (writes only inside your home folder):

   ```sh
   git clone https://github.com/harrycnguyen/monitor-brightness-ubuntu
   cd monitor-brightness-ubuntu
   packaging/install-user.sh --autostart    # leave out --autostart to start it by hand
   ```

3. Start **Monitor Brightness** from Activities (or log out and in once if you used `--autostart`). A sun icon appears in the top bar; click it to show or hide the sliders.

Don't move or delete the cloned folder: the launcher runs the code from there. To remove everything: `packaging/install-user.sh --uninstall`.

### Tray icon

- Click the icon to show or hide the window. Closing the window keeps the app in the tray.
- The icon's menu has "Show brightness controls" and "Quit".
- Ubuntu's GNOME session ships the AppIndicator extension that displays the icon. Without a tray host (extension off, other desktops) the window just opens normally.
- Only one copy runs at a time; starting it again shows the running one's window. After updating the code, quit the old copy first (`pkill -f monitor_brightness`), or you will keep seeing the old behaviour.
- The launcher borrows the `i2c` group with `sg` when your session doesn't have it yet, so external monitors work before you log out and back in.

## Command line

The launcher installs a `monitor-brightness` command (in `~/.local/bin`). Without installing, run `PYTHONPATH=src python3 -m monitor_brightness ...` from the repo.

```sh
monitor-brightness doctor               # checks ddcutil, i2c-dev and permissions, says how to fix
monitor-brightness list                 # index, id, current %, name (--json for scripts)
monitor-brightness set 40               # all displays
monitor-brightness set 70 -d 2          # one display: index, id (ddc:1) or part of the name (lg)
monitor-brightness up 10                # also: down 10. Bind these to GNOME keyboard shortcuts
monitor-brightness gui                  # tray icon + window (--background starts in the tray only,
                                        #   --debug prints tray/D-Bus activity)
```

## Troubleshooting

- **External monitor missing from the list:** run `monitor-brightness doctor`. Common causes are `ddcutil` not installed, `i2c-dev` not loaded, or no access to `/dev/i2c-*`. Some docks, DisplayLink adapters and HDMI ports don't pass DDC at all.
- **Slider reacts slowly:** monitors take tens to hundreds of milliseconds per DDC write. The app only sends the latest slider value while one is in flight.
- **No icon in the top bar:** check that the `ubuntu-appindicators` extension is enabled (`gnome-extensions list --enabled`), then run `monitor-brightness gui --debug` and look for `registered with the watcher`.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The tests use fake `ddcutil`/`xrandr` output and need no hardware or display. The window and tray need GTK 4 and libadwaita 1.0 or newer (no newer widgets are used, so Ubuntu 22.04 works).

Layout: `ddc.py`, `backlight.py` and `xrandr.py` are the backends, `manager.py` finds displays, `writer.py` coalesces slider writes, `tray.py` speaks the StatusNotifierItem and dbusmenu D-Bus protocols directly (the usual AppIndicator library is GTK 3 only), `gui.py` is the window and app, `cli.py` is the command line.

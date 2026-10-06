# monitor-brightness-ubuntu

Change the brightness of each monitor separately on Ubuntu, like the core feature of [Lunar](https://lunar.fyi) on macOS.

- External monitors: real brightness over DDC/CI (via `ddcutil`).
- Laptop screen: `/sys/class/backlight` (through logind, no root needed).
- Monitors without DDC: software dimming with `xrandr`, **X11 sessions only**. GNOME on Wayland needs a Shell extension for this, which isn't written yet.

Scope is brightness only. See the plan in the project files for what was left out on purpose.

## Setup

```sh
sudo apt install ddcutil
sudo modprobe i2c-dev
echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf
sudo groupadd --system i2c 2>/dev/null; sudo usermod -aG i2c $USER   # then log out and in
```

For the window: `sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`.

```sh
pip install -e .          # or run with PYTHONPATH=src python3 -m monitor_brightness
monitor-brightness doctor # checks the setup above
```

## Use

```sh
monitor-brightness list                 # index, id, current %, name
monitor-brightness set 40               # all displays
monitor-brightness set 70 -d 2          # by index, id (ddc:1) or part of the name (dell)
monitor-brightness up 10 / down 10      # bind these to GNOME keyboard shortcuts
monitor-brightness gui                  # one slider per display
```

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

The tests use fake `ddcutil`/`xrandr` output. Nothing has been run against real monitors or the GTK window yet; that needs an Ubuntu desktop.

# Gen5W emulator

Experimental tools for running Gen5W Android userspace on a PC, with a native
emulator window, touch input, a minimal MICOM simulator, and ZIP-backed virtual USB.
Firmware, OEM applications, keys, SDKs, kernel binaries, and personal logs are not included.

## Host support

Validation snapshot: November 5, 2026.

| Host | Verified scope |
| --- | --- |
| Apple Silicon macOS | Boot, GUI, GPU rendering, touch, MICOM, and virtual USB with Android Emulator 36.4.10 |
| Windows x86_64 | Boot and selected UI captures through a separate SDK Tools 25.2.5 runner; no equivalent Mac USB interface |
| Linux | Public kernel builds only; no VM launcher provided |

Image preparation is specific to **V039**. Hash and byte checks prevent applying
patches to unsupported inputs. This is not a generic firmware converter.
Seatbelt, AppKit, and hdiutil are macOS-specific; the Windows runner uses Windows Firewall.

## Run on macOS

Requires Python 3.11+ and an ARM64 Android SDK containing the ARM32 QEMU2 engine.
Keep prepared inputs and build artifacts in a private data directory:

```sh
cd /path/to/gen5w-emulator
export GEN5W_DATA_DIR=/path/to/private-data
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
python3 run_mac.py --usb
```

The data directory contains `build/`, `inputs/`, and `deps/`. USB mode uses the
prepared GPU system image, USB ramdisk, kernel, and verification JSON files under
`build/`, plus `userdata.img` and `build.prop` under `deps/api19/armeabi-v7a/`.
See `run_mac.main` for file names. Firmware acquisition and decryption are outside this guide.

Without `GEN5W_DATA_DIR`, data defaults to the repository root. You can also use
`--data-dir` and `--sdk`. Display, guest resources, and ports are configurable:

```sh
python3 run_mac.py --help
python3 run_mac.py --usb --display-size 1920 720 --density 240 --cpus 2 --memory 1024
```

More guest CPUs do not guarantee parallel execution or better performance.
Wait for `BOOT_COMPLETED=1` in the terminal, then complete the initial screens manually.
If the Welcome application remains on a black screen:

```sh
"$ANDROID_SDK_ROOT/platform-tools/adb" -P 5041 -s emulator-5588 shell am force-stop com.mobis.welcome
"$ANDROID_SDK_ROOT/platform-tools/adb" -P 5041 -s emulator-5588 shell am start -n com.hkmc.app.nmode.ui/.NMode_MainActivity
```

These ADB examples use the launcher's default ports; adjust them if you change the ports.
Close the emulator window or press Ctrl-C to stop. Guest `/data` and `/cache` use
tmpfs, so application state is lost on the next cold start.

## Virtual USB on macOS

With Xcode Command Line Tools installed, build the app using the same data directory:

```sh
python3 build_usb_app.py
open 'build/Gen5W USB.app'
```

- **Insert:** select a ZIP to create and attach an independent FAT32 disk snapshot. Nested ZIPs stay compressed.
- **Eject:** unmount the guest filesystem before removing the device. If unmounting fails, the device stays attached.

Editing the original ZIP after insertion does not change the attached disk.
The app uses the data directory and Python location selected at build time;
rebuild it if those locations change. Use `--data-dir` and `--output` to set them.

## Run on Windows

Requires Python 3.11+, prepared inputs, and SDK Tools 25.2.5.
Run from an administrator PowerShell. This runner performs headless boot and capture trials:

```powershell
cd C:\path\to\gen5w-emulator
.\start_windows.ps1 -DataDir C:\path\to\private-data
```

Use `-ToolsDir`, `-Adb`, and `-ImageDir` for installation paths, and
`-EmulatorPort`, `-AdbPort`, and `-ConsolePort` for ports. Direct Python invocation
also requires outbound firewall rules covering the same emulator executables.

## Preparation and limitations

The `prepare_*.py` tools also use `GEN5W_DATA_DIR`. Place the compiled MICOM helper
and external CPIO helpers in its `build/` and `reference/` directories.
GPU preparation finds `debugfs` on PATH, or accepts `--debugfs`.
Build the public kernel on Linux x86_64 with:

```sh
bash build_usb_kernel.sh /absolute/build/directory
```

Public source revisions are pinned in `reference-sources.json` and the build script.
The CPIO helpers are based on the [Stinger project](https://github.com/hdrsd/gen5-emulator-stinger).

MICOM simulation provides stationary status and selected gauge data, not a real
vehicle MCU or CAN bus. Unimplemented commands are not reported as successful.
Navigation, wireless, audio, vehicle functions, and long-term stability remain unverified.
The CPU runs through TCG translation; GPU acceleration is separate from CPU virtualization.

The launchers isolate guest networking and use working copies of the images.
These tools are not for installation on a vehicle. Use only inputs you are authorized
to use. External SDK, kernel, and reference-code licenses apply separately.
Keep the input and output exclusions in `.gitignore`.

Run the tool checks on macOS:

```sh
python3 -m unittest -v
```

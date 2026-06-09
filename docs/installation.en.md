# Installation

## Python Package

Install DropLogic from a source checkout with:

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

For development, use editable mode:

```bash
pip install -e .
```

## DMLite Native Runtime

The Python package contains the DropLogic adapter code. Native hardware control needs the matching DropLogic runtime assets for the host operating system and CPU architecture. These native files are distributed separately from the public Python source tree.

`DMLite` is supported on these hosts when the matching runtime is installed:

| Host | Runtime file |
| --- | --- |
| Windows x86_64 | `electrode_matrix/dmlite/sdk.dll` |
| macOS Apple Silicon | `electrode_matrix/dmlite/sdk.dylib` |
| Linux x86_64 | `electrode_matrix/dmlite/linux-x86_64/sdk.so` |
| Raspberry Pi OS 64-bit | `electrode_matrix/dmlite/linux-aarch64/sdk.so` |
| Raspberry Pi OS 32-bit | `electrode_matrix/dmlite/linux-armv7l/sdk.so` |

DropLogic resolves these files from the installed runtime folder, from `DROPLOGIC_RUNTIME_DIR`, or from `vendor_bin/electrode_matrix/dmlite/` when working from a local source checkout.

If the file for the current OS or architecture is missing, `DMLite()` raises a runtime error instead of silently falling back to the wrong backend.

## Linux And Raspberry Pi Dependencies

On Debian, Ubuntu, and Raspberry Pi OS, install the `libusb` runtime package:

```bash
sudo apt update
sudo apt install -y libusb-1.0-0
```

If you are building the DMLite runtime from source on Linux or Raspberry Pi, install the development package too:

```bash
sudo apt install -y build-essential pkg-config libusb-1.0-0-dev python3
```

For non-root USB access on Linux or Raspberry Pi, install the DMLite udev rule supplied with the runtime source package. From that runtime source package directory, run:

```bash
sudo cp udev/99-dmlite.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and reconnect the DMLite controller.

## macOS Dependency

The current macOS runtime is built for Apple Silicon. Install `libusb` with Homebrew unless your runtime package bundles it:

```bash
brew install libusb
```

## Smoke Test

From the repository root, run:

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

If DropLogic was installed with `pip install .`, `PYTHONPATH=.` is not usually needed:

```bash
python3 examples/DMLite_example.py
```

Use the simulator example when you want to test planning and visualization without connected hardware:

```bash
python3 examples/simulator_example.py
```

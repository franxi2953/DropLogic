# 安裝

## Python 套件

由源碼 checkout 安裝 DropLogic：

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

做開發時可以用 editable mode：

```bash
pip install -e .
```

## DMLite 原生 Runtime

Python 套件入面有 DropLogic 嘅適配層程式碼。要控制真實硬件，仲需要同主機作業系統同 CPU 架構相配嘅 DropLogic 原生 runtime assets。呢啲原生檔案唔會放喺公開 Python 源碼樹入面，而係另外分發。

裝好相應 runtime 之後，`DMLite` 支援以下主機：

| 主機 | Runtime 檔案 |
| --- | --- |
| Windows x86_64 | `electrode_matrix/dmlite/sdk.dll` |
| macOS Apple Silicon | `electrode_matrix/dmlite/sdk.dylib` |
| Linux x86_64 | `electrode_matrix/dmlite/linux-x86_64/sdk.so` |
| Raspberry Pi OS 64-bit | `electrode_matrix/dmlite/linux-aarch64/sdk.so` |
| Raspberry Pi OS 32-bit | `electrode_matrix/dmlite/linux-armv7l/sdk.so` |

DropLogic 會由已安裝嘅 runtime 資料夾、`DROPLOGIC_RUNTIME_DIR`，或者本地源碼 checkout 入面嘅 `vendor_bin/electrode_matrix/dmlite/` 搵呢啲檔案。

如果目前作業系統或架構所需嘅檔案唔存在，`DMLite()` 會拋出 runtime error，而唔會靜默載入錯誤 backend。

## Linux 同 Raspberry Pi 依賴

喺 Debian、Ubuntu 同 Raspberry Pi OS 上，先安裝 `libusb` runtime 套件：

```bash
sudo apt update
sudo apt install -y libusb-1.0-0
```

如果要喺 Linux 或 Raspberry Pi 由源碼編譯 DMLite runtime，亦要安裝開發套件：

```bash
sudo apt install -y build-essential pkg-config libusb-1.0-0-dev python3
```

如果想喺 Linux 或 Raspberry Pi 唔用 `sudo` 都可以存取 USB，請安裝 runtime 源碼包提供嘅 DMLite udev rule。喺該 runtime 源碼包目錄入面執行：

```bash
sudo cp udev/99-dmlite.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

之後拔走再重新插入 DMLite 控制器。

## macOS 依賴

目前 macOS runtime 係為 Apple Silicon 編譯。除非 runtime 套件已經包埋 `libusb`，否則請用 Homebrew 安裝：

```bash
brew install libusb
```

## 快速測試

由倉庫根目錄執行：

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

如果 DropLogic 已經用 `pip install .` 安裝，通常唔需要 `PYTHONPATH=.`：

```bash
python3 examples/DMLite_example.py
```

如果只想測試規劃同視覺化，而唔連接硬件，請執行模擬器範例：

```bash
python3 examples/simulator_example.py
```

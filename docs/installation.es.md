# Instalacion

## Paquete Python

Instala DropLogic desde un checkout del codigo con:

```bash
git clone https://github.com/franxi2953/DropLogic.git
cd DropLogic
pip install .
```

Para desarrollo, usa modo editable:

```bash
pip install -e .
```

## Runtime Nativo De DMLite

El paquete Python contiene el codigo adaptador de DropLogic. El control de hardware real necesita los assets nativos de runtime correspondientes al sistema operativo y arquitectura de CPU. Estos archivos nativos se distribuyen por separado del arbol publico de codigo Python.

`DMLite` esta soportado en estos hosts cuando el runtime correspondiente esta instalado:

| Host | Archivo de runtime |
| --- | --- |
| Windows x86_64 | `electrode_matrix/dmlite/sdk.dll` |
| macOS Apple Silicon | `electrode_matrix/dmlite/sdk.dylib` |
| Linux x86_64 | `electrode_matrix/dmlite/linux-x86_64/sdk.so` |
| Raspberry Pi OS 64-bit | `electrode_matrix/dmlite/linux-aarch64/sdk.so` |
| Raspberry Pi OS 32-bit | `electrode_matrix/dmlite/linux-armv7l/sdk.so` |

DropLogic resuelve estos archivos desde la carpeta de runtime instalada, desde `DROPLOGIC_RUNTIME_DIR`, o desde `vendor_bin/electrode_matrix/dmlite/` cuando trabajas en un checkout local del repositorio.

Si falta el archivo para el sistema operativo o la arquitectura actual, `DMLite()` lanza un error de runtime en vez de intentar cargar un backend incorrecto.

## Dependencias En Linux Y Raspberry Pi

En Debian, Ubuntu y Raspberry Pi OS, instala el paquete runtime de `libusb`:

```bash
sudo apt update
sudo apt install -y libusb-1.0-0
```

Si vas a compilar el runtime de DMLite desde fuente en Linux o Raspberry Pi, instala tambien el paquete de desarrollo:

```bash
sudo apt install -y build-essential pkg-config libusb-1.0-0-dev python3
```

Para acceso USB sin `sudo` en Linux o Raspberry Pi, instala la regla udev incluida con el paquete fuente del runtime. Desde el directorio de ese paquete fuente, ejecuta:

```bash
sudo cp udev/99-dmlite.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Despues desconecta y reconecta el controlador DMLite.

## Dependencia En macOS

El runtime actual de macOS esta compilado para Apple Silicon. Instala `libusb` con Homebrew salvo que tu paquete de runtime ya lo incluya:

```bash
brew install libusb
```

## Prueba Rapida

Desde la raiz del repositorio, ejecuta:

```bash
PYTHONPATH=. python3 examples/DMLite_example.py
```

Si DropLogic se instalo con `pip install .`, normalmente no hace falta `PYTHONPATH=.`:

```bash
python3 examples/DMLite_example.py
```

Usa el ejemplo de simulador cuando quieras probar planificacion y visualizacion sin hardware conectado:

```bash
python3 examples/simulator_example.py
```

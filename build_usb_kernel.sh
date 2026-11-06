#!/usr/bin/env bash
# Build public sources on Linux x86_64. No OEM files are used.
set -euo pipefail

task_root=${1:?Usage: build_usb_kernel.sh /absolute/build/directory}
mkdir -p "$task_root"
task_root=$(cd "$task_root" && pwd)
kernel_commit=8d8fd409b4391758301a0be663d2808e99234e6f
gcc_commit=0390252b6bcc6217966ade31d07f8b12f6f78f89
test "$(uname -m)" = x86_64
test ! -e "$task_root/src"
test ! -e "$task_root/toolchain"
mkdir "$task_root/src" "$task_root/toolchain"
curl -fL -o "$task_root/kernel.tar.gz" \
  "https://android.googlesource.com/kernel/goldfish/+archive/$kernel_commit.tar.gz"
curl -fL -o "$task_root/gcc.tar.gz" \
  "https://android.googlesource.com/platform/prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9/+archive/$gcc_commit.tar.gz"
tar xzf "$task_root/kernel.tar.gz" -C "$task_root/src"
tar xzf "$task_root/gcc.tar.gz" -C "$task_root/toolchain"

cd "$task_root/src"
build=(make ARCH=arm HOSTCFLAGS=-fcommon
       CROSS_COMPILE="$task_root/toolchain/bin/arm-linux-androideabi-"
       O="$task_root/out")
"${build[@]}" ranchu_defconfig
scripts/config --file "$task_root/out/.config" \
  -e PCI -e PCI_HOST_GENERIC -e USB -e USB_XHCI_HCD -e USB_XHCI_PCI \
  -e SCSI -e BLK_DEV_SD -e USB_STORAGE -e NLS_UTF8 \
  -e ANDROID_BINDER_IPC_32BIT -d DEBUG_INFO
"${build[@]}" olddefconfig
"${build[@]}" -j"${JOBS:-8}" zImage

python3 - "$task_root" "$kernel_commit" "$gcc_commit" <<'PY'
import hashlib
import json
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
config = root / 'out/.config'
required = ('PCI_HOST_GENERIC', 'USB_XHCI_HCD', 'USB_XHCI_PCI', 'USB_STORAGE',
            'BLK_DEV_SD', 'ANDROID_BINDER_IPC_32BIT', 'ASHMEM', 'EXT4_FS',
            'SECURITY_SELINUX', 'GOLDFISH_PIPE', 'FB_GOLDFISH', 'VFAT_FS')
values = config.read_text().splitlines()
for setting in required:
    if f'CONFIG_{setting}=y' not in values:
        raise RuntimeError(f'Required kernel setting missing: CONFIG_{setting}=y')
kernel = root / 'usb-kernel-318'
shutil.copyfile(root / 'out/arch/arm/boot/zImage', kernel)
report = {'kernel_commit': sys.argv[2], 'gcc_commit': sys.argv[3],
          'kernel_sha256': hashlib.sha256(kernel.read_bytes()).hexdigest(),
          'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest()}
(root / 'usb-kernel-verification.json').write_text(json.dumps(report, indent=2) + '\n')
shutil.copyfile(config, root / 'usb-kernel-318.config')
print(json.dumps(report, indent=2))
PY

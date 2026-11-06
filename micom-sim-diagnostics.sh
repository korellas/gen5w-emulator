echo VM_ROOT_DIAG_BEGIN
id
getenforce
echo 0 > /proc/sys/kernel/printk
cat /proc/uptime
getprop vm.logger.ready
getprop vm.micom.ready
getprop init.svc.vm-micom
getprop sys.boot_completed
ps
cat /proc/net/unix
ls -lZ /sbin/vm-micom
cat /data/local/tmp/vm-micom.log
chmod 0644 /data/local/tmp/vm-micom.log
chmod 0755 /data/local/tmp/vm-log-capture
chmod 0644 /data/local/tmp/vm-log-capture/*.raw
dumpsys com.hkmc.micom.system
cat /proc/meminfo
for proc in /proc/[0-9]*; do
    read name < "$proc/comm"
    case "$name" in
        vm-micom|system_server|surfaceflinger|zygote)
            echo "PROC $proc $name"
            cat "$proc/stat"
            cat "$proc/status"
            ;;
    esac
done
dmesg
echo VM_ROOT_DIAG_END

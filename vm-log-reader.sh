#!/system/bin/sh
# Off-car diagnostic reader. The descriptor stays open after capture reaches its limit.
export PATH=/system/bin:/system/xbin
out=/data/local/tmp/vm-log-capture
mkdir "$out" || exit 1
chmod 0750 "$out" || exit 1
umask 0077
pids=
fail() {
    echo "FAILED: $*" >> "$out/status"
    setprop vm.logger.failed 1
    exit 1
}
for channel in main radio events system mobis; do
    (
        exec 3<>"/vm-logger/$channel" || exit 1
        echo ready > "$out/$channel.ready" || exit 1
        dd bs=4096 count=2048 <&3 > "$out/$channel.raw" 2> "$out/$channel.dd-status" || exit 1
        echo capture-limit-reached >> "$out/$channel.dd-status"
        cat <&3 > /dev/null
        exit 1
    ) &
    pids="$pids $!"
done
for channel in main radio events system mobis; do
    attempts=0
    while [ ! -f "$out/$channel.ready" ]; do
        for pid in $pids; do
            kill -0 "$pid" || fail "reader exited before ready"
        done
        attempts=$((attempts + 1))
        [ "$attempts" -lt 30 ] || fail "reader ready timeout"
        sleep 1
    done
done
echo "READY: read-write descriptors open on all channels" >> "$out/status"
setprop vm.logger.ready 1 || fail "ready property rejected"
while :; do
    for pid in $pids; do
        kill -0 "$pid" || fail "reader exited during collection"
    done
    sleep 1
done

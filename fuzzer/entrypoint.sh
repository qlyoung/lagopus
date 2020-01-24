#!/bin/bash
echo "called with: $@"

# just for testing purposes, normally this will be created for us
JOBDIR=$LAGOPUS_JOB_ID-$(date +%s)
mkdir -p $JOBDIR
cd $JOBDIR

# Target binary should be placed at /opt/fuzz/target
TARGET="./target"
# Corpus should be placed at /opt/fuzz/corpus
CORPUS="./corpus"
# Results directory should be externally mounted at /opt/fuzz/results
# For AFL this needs to be fixed as AFL dislikes NFS
RESULT="./results"
# afl-multicore config file should be placed at /opt/fuzz/target.conf when
# using AFL
AFLMCC="./target.conf"

DRIVER=$1 # 'afl', 'libfuzzer'

if [ $# -gt 1 ]; then
  CORES=$2
else
  CORES=2
fi


if [ ! -f "$(pwd)/$TARGET" ]; then
  printf "Target $(pwd)/$TARGET does not exist; exiting\n"
  exit 1
fi

if [ ! -d "$(pwd)/$CORPUS" ]; then
  printf "Corpus directory $(pwd)/$TARGET does not exist; exiting\n"
  exit 1
fi

if [ "$DRIVER" == "afl" -a ! -f "$(pwd)/$AFLMCC" ]; then
  printf "afl-multicore config file $(pwd)/$AFLMCC does not exist; exiting\n"
  exit 1
fi

if [ "$DRIVER" == "afl" ]; then
  # Check appropriate system parameters
  # swapoff -a
  # aka sysctl -w kernel.core_pattern=core
  # but we may not have `sysctl` for some reason
  # echo core >/proc/sys/kernel/core_pattern
  # this path doesn't seem to exist in virtualized devices (kvm, docker)
  # bash -c 'cd /sys/devices/system/cpu; echo performance | tee cpu*/cpufreq/scaling_governor'
  afl-multicore -s 1 -v -c $AFLMCC start $CORES
elif [ "$DRIVER" == "libfuzzer" ]; then
  ./target -rss_limit_mb=0 -jobs=$CORES -workers=$CORES $RESULT $CORPUS &
else
  printf "Fuzzing driver '$DRIVER' unsupported; exiting\n"
  exit 1
fi

# health check indicator
touch started

# Loop on pushing out stats
FUZZERS_ALIVE=1

while [ "$FUZZERS_ALIVE" -ne "0" ]; do
	FUZZERS_ALIVE=$(ps -ef | grep -v "grep" | grep "$TARGET" | wc -l) 
	CPU_USAGE=$(top -b -n2 -p 1 | fgrep "Cpu(s)" | tail -1 | awk -F'id,' -v prefix="$prefix" '{ split($1, vs, ","); v=vs[length(vs)]; sub("%", "", v); printf "%s%.1f%%\n", prefix, 100 - v }')
	MEM_USAGE=$(free -h | grep "Mem" | tr -s ' ' | cut -d' ' -f3)
	printf "%d fuzzers alive, cpu: %s, mem: %s\n" $FUZZERS_ALIVE $CPU_USAGE $MEM_USAGE
	sleep 1
done

printf "No fuzzers alive, exiting.\n"

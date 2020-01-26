#!/bin/bash
echo "called with: $@"

if [ "$FUZZER_TIMEOUT" != "" ]; then
  echo "Timeout: $FUZZER_TIMEOUT"
else
  echo "No timeout specified"
fi

# record start time to compute elapsed time later
STARTTIME="$(date -u +%s)"

# Development jobs ------------
JOBDIR=/jobdata/
mkdir -p $JOBDIR
cd $JOBDIR
wget http://jobserver:80/testjob.zip -O target.zip
# -----------------------------
unzip target.zip

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

mkdir -p $RESULT

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
  ./target -detect_leaks=0 -rss_limit_mb=0 -jobs=$CORES -workers=$CORES $RESULT $CORPUS &
else
  printf "Fuzzing driver '$DRIVER' unsupported; exiting\n"
  exit 1
fi

# health check indicator
touch started

# Loop on pushing out stats
FUZZERS_ALIVE=1
ELAPSED_TIME=$(($(date -u +%s) - $STARTTIME))

while [ "$FUZZERS_ALIVE" -ne "0" -a ! -f /shouldexit -a ! $ELAPSED_TIME -gt $FUZZER_TIMEOUT ]; do
	FUZZERS_ALIVE=$(ps -ef | grep -v "grep" | grep "$TARGET" | wc -l) 
	ELAPSED_TIME=$(($(date -u +%s) - $STARTTIME))
	CPU_USAGE=$(mpstat 2 1 | awk '$12 ~ /[0-9.]+/ { print 100 - $12"%" }' | tail -n 1)
	MEM_USAGE=$(free -h | grep "Mem" | tr -s ' ' | cut -d' ' -f3)
	printf "%d fuzzers alive, cpu: %s, mem: %s\n" $FUZZERS_ALIVE $CPU_USAGE $MEM_USAGE
	sleep 1
done

if [ "$FUZZERS_ALIVE" == "0" ]; then
  printf "No fuzzers alive, exiting.\n"
fi

if [ $ELAPSED_TIME -gt $FUZZER_TIMEOUT ]; then
  printf "Elapsed time %d greater than specified timeout %d\n" $ELAPSED_TIME $FUZZER_TIMEOUT
fi

if [ "$FUZZERS_ALIVE" == "0" ]; then
  printf "No fuzzers alive, exiting.\n"
fi

if [ -f /shouldexit ]; then
  printf "Graceful exit requested, exiting.\n"
fi

exit 0

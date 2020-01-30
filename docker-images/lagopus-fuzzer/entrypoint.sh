#!/bin/bash

# Required environment variables:
# - JOBDATA: absolute path to directory with target.zip
# - DRIVER: the fuzzing driver, one of [afl, libfuzzer]
#
# Optional environment variables:
# - FUZZER_TIMEOUT

# Setup -------------------

echo "called with: $@"

if [ ! -d "$JOBDATA" ]; then
  printf "Job directory %s does not exist; exiting\n" $JOBDATA
  ls /
  exit 1
fi
printf "Job directory: %s\n" $JOBDATA

# timeout
if [ "$FUZZER_TIMEOUT" == "" ]; then
  echo "No timeout specified"
  FUZZER_TIMEOUT=3600
fi
printf "Timeout: %d seconds\n" $FUZZER_TIMEOUT

# set cores
if [ "$CORES" == "" ]; then
  echo "No core count specified"
  CORES=2
fi
printf "Using %d cores" $CORES

# record start time to compute elapsed time later
STARTTIME="$(date -u +%s)"

# Run ---------------------

mkdir -p $WORKDIR
cp $JOBDATA/target.zip $WORKDIR/
# wget http://jobserver:80/testjob.zip -O target.zip

cd $WORKDIR

unzip target.zip

TARGET="./target"
CORPUS="./corpus"
RESULT="./results"
# afl-multicore config file should be placed at $JOBDATA/target.conf when using
# AFL
AFLMCC="./target.conf"

mkdir -p $RESULT

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

if ["$DRIVER" == "afl" ]; then
	afl-multikill -S $(jq .session $AFLMCC)
fi

# collect results based on the driver
mkdir jobresults
mkdir jobresults/corpus     # for generated corpus
mkdir jobresults/crashes    # for bug-triggering corpus inputs
mkdir jobresults/misc       # for miscellaneous job foo

if [ "$DRIVER" == "afl" ]; then
  # in the afl case, afl uses /jobdata/results as its sync dir

  # Verify, deduplicate and classify crashes
  printf "Analyzing crashes...\n"
  afl-collect -d ./jobresults/crashes/crashes.db -e gdb_script -r -rr -j $CORES $RESULT ./jobresults/crashes/ -- $TARGET

  # Minimize corpus
  printf "Minimizing corpus...\n"
  afl-minimize -c ./jobresults/corpus --cmin --cmin-mem-limit=none --tmin --tmin-mem-limit=none -j $CORES $RESULT -- $TARGET

  # FIXME: these will overwrite each other in the copy
  printf "Copying miscellaneous datum...\n"
  find $RESULT -type f -name 'fuzzer_stats' | xargs cp -t jobresults/misc

elif [ "$DRIVER" == "libfuzzer" ]; then
  # in the libfuzzer case, corpus data is written to /jobdata/results

  cp -r $RESULT/* jobresults/misc/
  # presently libfuzzer kills itself when it finds a bug, and just writes a
  # normal corpus file but prefixed with the type of bug it found
  cp -r $RESULT/crash* jobresults/crashes/
  cp -r $RESULT/leak* jobresults/crashes/
  cp -r $RESULT/*slow* jobresults/crashes/
  cp fuzz*.log jobresults/misc/

fi

# upload results
zip -r jobresults.zip jobresults

cp jobresults.zip $JOBDATA

exit 0

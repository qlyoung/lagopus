#!/bin/bash
#
# Fuzz a target for a time, then analyze crashes, minimize corpus, zip results
# and exit.
#
# Required environment variables:
# - JOBDATA: absolute path to directory with target.zip
# - DRIVER: the fuzzing driver, one of [afl, libFuzzer]
#
# Optional environment variables:
# - FUZZER_TIMEOUT: how long to fuzz for (default 3600s)
# - CORES: how many jobs to use (default: 2)
# - INFLUXDB: if specified, fuzzing stats are posted to the specified InfluxDB
#   instance. The format must be "<host>:<port>:<database>.
# - INFLUXDB_DB: the database to insert into; must be set if INFLUXDB is set
# - INFLUXDB_MEASUREMENT: the measurement to store stats into; must  be set if INFLUXDB is set

# Setup -------------------

if [ ! -d "$JOBDATA" ]; then
  printf "Job directory %s does not exist; exiting\n" "$JOBDATA"
  ls /
  exit 1
fi
printf "Job directory: %s\n" "$JOBDATA"

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

if [ "$INFLUXDB" != "" ]; then
  INFLUXDB_HOST=$(echo "$INFLUXDB" | cut -d':' -f1)
  INFLUXDB_PORT=$(echo "$INFLUXDB" | cut -d':' -f2)
  if [[ -z "$INFLUXDB_DB" ]]; then
    echo "Specified InfluxDB host but not a database; exiting"
    exit 1
  fi
fi

# record start time to compute elapsed time later
STARTTIME="$(date -u +%s)"

# Run ---------------------

mkdir -p "$WORKDIR"
cp "$JOBDATA/target.zip" "$WORKDIR/"
# wget http://jobserver:80/testjob.zip -O target.zip

cd "$WORKDIR" || exit 1

unzip target.zip

TARGET="./target"
CORPUS="./corpus"
RESULT="./results"
# afl-multicore config file should be placed at $JOBDATA/target.conf when using
# AFL
AFLMCC="./target.conf"

mkdir -p $RESULT

if [ ! -f "$(pwd)/$TARGET" ]; then
  printf "Target %s/%s does not exist; exiting\n" "$(pwd)" "$TARGET"
  exit 1
fi

if [ ! -d "$(pwd)/$CORPUS" ]; then
  printf "Corpus directory %s/%s does not exist; exiting\n" "$(pwd)" "$TARGET"
  exit 1
fi

if [ "$DRIVER" == "afl" ] && [ ! -f "$(pwd)/$AFLMCC" ]; then
  printf "afl-multicore config file %s/%s does not exist; exiting\n" "$(pwd)" "$(AFLMCC)"
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
  COUNTFUZZER_CMD="pgrep -c afl-fuzz"
elif [ "$DRIVER" == "libFuzzer" ]; then
  ./target -max_total_time=$FUZZER_TIMEOUT -rss_limit_mb=0 -jobs=$CORES -workers=$CORES $CORPUS &
  COUNTFUZZER_CMD="pgrep -fc rss_limit_mb"
else
  printf "Fuzzing driver '%s' unsupported; exiting\n" "$DRIVER"
  exit 1
fi

# health check indicator
touch started

# Loop on pushing out stats
FUZZERS_ALIVE=1
ELAPSED_TIME=$(($(date -u +%s) - STARTTIME))

while [ "$FUZZERS_ALIVE" -ne "0" ] && [ ! -f /shouldexit ] && [ ! $ELAPSED_TIME -gt $FUZZER_TIMEOUT ]; do
	FUZZERS_ALIVE=$(eval "$COUNTFUZZER_CMD")
	ELAPSED_TIME=$(($(date -u +%s) - STARTTIME))
	CPU_USAGE=$(mpstat 2 1 | awk '$12 ~ /[0-9.]+/ { print 100 - $12"%" }' | tail -n 1)
	MEM_USAGE=$(free -h | grep "Mem" | tr -s ' ' | cut -d' ' -f3)
	printf "%d fuzzers alive, cpu: %s, mem: %s\n" "$FUZZERS_ALIVE" "$CPU_USAGE" "$MEM_USAGE"

	if [ ! -z "$INFLUXDB" ]; then
          if [ "$DRIVER" == "afl" ]; then
	    bash /monitor-afl.sh -i "$INFLUXDB_HOST" -p $INFLUXDB_PORT -d "$INFLUXDB_DB" -m "$INFLUXDB_MEASUREMENT" $RESULT
          elif [ "$DRIVER" == "libFuzzer" ]; then
	    bash /monitor-libfuzzer.sh -i "$INFLUXDB_HOST" -p $INFLUXDB_PORT -d "$INFLUXDB_DB" -m "$INFLUXDB_MEASUREMENT"
	  fi
	fi
	sleep 1
done

if [ "$FUZZERS_ALIVE" == "0" ]; then
  printf "No fuzzers alive, exiting.\n"
fi

if [ $ELAPSED_TIME -gt $FUZZER_TIMEOUT ]; then
  printf "Elapsed time %d greater than specified timeout %d\n" "$ELAPSED_TIME" "$FUZZER_TIMEOUT"
fi

if [ "$FUZZERS_ALIVE" == "0" ]; then
  printf "No fuzzers alive, exiting.\n"
fi

if [ -f /shouldexit ]; then
  printf "Graceful exit requested, exiting.\n"
fi

if [ "$DRIVER" == "afl" ]; then
	afl-multikill -S $(jq -r .session $AFLMCC)
elif [ "$DRIVE" == "libFuzzer" ]; then
	# FIXME: This doesn't work when the binary has custom handlers for
	# SIGUSR1, and while good fuzzing targets should already have taken
	# care of this, we should still detect when they don't die and
	# forcefully kill them
	kill -SIGUSR1 "$TARGET"
fi

# collect results based on the driver
mkdir jobresults
mkdir jobresults/corpus     # for generated corpus
mkdir jobresults/crashes    # for bug-triggering corpus inputs
mkdir jobresults/misc       # for miscellaneous job foo

# Collect and analyze crashes
sqlite3 ./jobresults/crashes/crashes.db "create table analysis (sample TEXT PRIMARY KEY, type TEXT, is_crash INTEGER, is_security_issue INTEGER, should_ignore INTEGER, backtrace TEXT, output TEXT, return_code INTEGER);"

if [ "$DRIVER" == "afl" ]; then
  # in the afl case, afl uses /jobdata/results as its sync dir

  # afl-collect will do some deduplication for us; it also has the ability to
  # do crash analysis via gdb exploitable, but in practice this doesn't work
  # very well - especially on *SAN binaries, which it sees as exiting cleanly
  # because stack dumping is performed by *SAN itself - so it's turned off in
  # favor of CF's implementation
  afl-collect -j $CORES $RESULT ./jobresults/crashes/ -- $TARGET
elif [ "$DRIVER" == "libFuzzer" ]; then
  # in the libFuzzer case, corpus data is written to /jobdata/results

  # presently libFuzzer kills itself when it finds a bug, and just writes a
  # normal corpus file but prefixed with the type of bug it found, into the
  # current directory
  cp -r ./crash* jobresults/crashes/
  cp -r ./leak* jobresults/crashes/
  cp -r ./*slow* jobresults/crashes/

  # logs - need to be copied before minimize, otherwise lf will overwrite them
  cp fuzz*.log jobresults/misc/
fi

for file in ./jobresults/crashes/*; do
  fname=$(basename "$file")
  if [ "$(basename "$file")" == "gdb_script" ] || [ "$(basename "$file")" == "crashes.db" ]; then continue; fi

  # run test case and collect output
  if [ "$DRIVER" == "afl" ]; then
    # FIXME: need to parse & use the actual execution line from target.conf
    $TARGET < "$file" &> output.txt
    EC=$?
  elif [ "$DRIVER" == "libFuzzer" ]; then
    # FIXME: need to use the same invocation format as the fuzz run
    $TARGET "$file" &> output.txt
    EC=$?
  fi

  # Perform some more analysis with ClusterFuzz's crash analysis tooling
  ANALYSIS_JSON=$(/analyzer/analyzer.py --outputfile output.txt --exitcode $EC)

  DB_SAMPLE="$fname"
  DB_TYPE="$(echo "$ANALYSIS_JSON" | jq -r .type)"
  DB_IS_CRASH="$(echo "$ANALYSIS_JSON" | jq .is_crash | sed -e 's/true/1/' -e 's/false/0/')"
  DB_IS_SECURITY_ISSUE="$(echo "$ANALYSIS_JSON" | jq .is_security_issue | sed -e 's/true/1/' -e 's/false/0/')"
  DB_SHOULD_IGNORE="$(echo "$ANALYSIS_JSON" | jq .should_ignore | sed -e 's/true/1/' -e 's/false/0/')"
  DB_BACKTRACE="$(echo "$ANALYSIS_JSON" | jq -r .stacktrace)"
  DB_OUTPUT="$(echo "$ANALYSIS_JSON" | jq -r .output)"
  DB_RC="$(echo "$ANALYSIS_JSON" | jq -r .return_code)"

  # we do what has to be done, not because we wish to, but because we must
  python3 - <<-EOF
	import sqlite3 as sq; c = sq.connect("jobresults/crashes/crashes.db");
	c.execute("insert into analysis (sample, type, is_crash, is_security_issue, should_ignore, backtrace, output, return_code) values (?, ?, ?, ?, ?, ?, ?, ?)", ("""$DB_SAMPLE""", """$DB_TYPE""", $DB_IS_CRASH, $DB_IS_SECURITY_ISSUE, $DB_SHOULD_IGNORE, """$DB_BACKTRACE""", """$DB_OUTPUT""", $DB_RC))
	c.commit(); c.close();
	EOF
done

# Minimize corpus
printf "Minimizing corpus...\n"

if [ "$DRIVER" == "afl" ]; then
  # TODO: afl-tmin is turned off because it takes so long
  afl-minimize -c ./jobresults/corpus --cmin --cmin-mem-limit=none -j $CORES $RESULT -- $TARGET

  # FIXME: these will overwrite each other in the copy
  printf "Copying miscellaneous datum...\n"
  find $RESULT -print0 -type f -name 'fuzzer_stats' | xargs cp -t jobresults/misc

elif [ "$DRIVER" == "libFuzzer" ]; then
  # afl-tmin type functionality is available via -minimize_crash, which might
  # be useful during the analysis step or here.
  mkdir minimized
  $TARGET -merge=1 -rss_limit_mb=0 -jobs=$CORES -workers=$CORES minimized $CORPUS

  cp -r $RESULT/* minimized/
  mv minimized jobresults/corpus/
fi

# upload results
zip -r jobresults.zip jobresults

cp jobresults.zip "$JOBDATA"

exit 0

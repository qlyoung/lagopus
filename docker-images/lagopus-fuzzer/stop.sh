#!/bin/bash
# Called to clean up after ourselves and gather results

# first - what driver are we running with?
if [ "$(ps -ef | grep -v "grep" | grep "afl-fuzz" | wc -l)" == "0" ]; then
  DRIVER="libfuzzer"
else
  DRIVER="afl"
fi

# collect results based on the driver
cd /jobdata

mkdir jobresults
mkdir jobresults/corpus     # for generated corpus
mkdir jobresults/crashes    # for bug-triggering corpus inputs
mkdir jobresults/misc       # for miscellaneous job foo

if [ "$DRIVER" == "afl" ]; then
  # in the afl case, afl uses /jobdata/results as its sync dir
  find ./results -type f -wholename '*crashes/*' | xargs cp -t jobresults/crashes
  find ./results -type f -wholename '*queue/*' | xargs cp -t jobresults/corpus
  # FIXME: these will overwrite each other in the copy
  find ./results -type f -name 'fuzzer_stats' | xargs cp -t jobresults/corpus
elif [ "$DRIVER" == "libfuzzer" ]; then
  # in the libfuzzer case, corpus data is written to /jobdata/results
  cp -r results/* jobresults/misc/
  # presently libfuzzer kills itself when it finds a bug, and just writes a
  # normal corpus file but prefixed with the type of bug it found
  cp -r results/crash* jobresults/crashes/
  cp -r results/leak* jobresults/crashes/
  cp -r results/*slow* jobresults/crashes/
  cp fuzz*.log jobresults/misc/
fi

zip -r jobresults.zip jobresults 

# tell entrypoint.sh it should die
touch /shouldexit

sleep 10

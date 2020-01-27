#!/bin/bash
# Called to clean up after ourselves and gather results

# collect results based on the driver
mkdir jobresults
mkdir jobresults/corpus     # for generated corpus
mkdir jobresults/crashes    # for bug-triggering corpus inputs
mkdir jobresults/misc       # for miscellaneous job foo

if [ "$DRIVER" == "afl" ]; then
  # in the afl case, afl uses /jobdata/results as its sync dir
  find ./results -type f -wholename '*crashes/*' | xargs cp -t jobresults/crashes
  find ./results -type f -wholename '*queue/*' | xargs cp -t jobresults/corpus
  # FIXME: these will overwrite each other in the copy
  find ./results -type f -name 'fuzzer_stats' | xargs cp -t jobresults/misc
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

cp jobresults.zip $JOBDATA

exit 0

#!/usr/bin/env python3

import argparse
import json
import pprint

from crash_analysis.crash_result import CrashResult


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputfile", type=str, help="crashing program output", required=True)
    parser.add_argument("--exitcode", type=int, help="crashing program exit code", required=True)
    parser.add_argument("--time", type=int, help="crash collection time, Unix timestamp", default=0)

    args = parser.parse_args()

    output = open(args.outputfile).read()

    cr = CrashResult(args.exitcode, args.time, output)

    result = {
            'type': cr.get_type(),
            'is_crash': cr.is_crash(),
            'is_security_issue': cr.is_security_issue(),
            'should_ignore': cr.should_ignore(),
            'stacktrace': cr.get_stacktrace(),
            'output': cr.output,
            'return_code': cr.return_code,
    }

    print(json.dumps(result, indent=4))

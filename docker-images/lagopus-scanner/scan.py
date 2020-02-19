#!/usr/bin/env python3
# Scan job directory and update database

import os
import sqlite3
import time
import pprint
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile
from collections import defaultdict

import mysql.connector

DBCONF = {
    "user": "root",
    "password": "lagopus",
    "host": "localhost",
    "database": "lagopus",
    "raise_on_warnings": True,
    "tables": ["jobs", "crashes"],
}


def process_jobresults(jobid, jobresult_zip, crashdb, cnx):
    """
    Read crashes.db and export crash information into MySQL for use by the
    server.

    :param jobid: name of the job we are processing, same as the job
                  directory
    :param jobresult_zip: jobresults.zip ZipFile
    :param crashdb: path to sqlite3 crashes.db
    :param cnx: database connection, or None to skip export
    """
    if not cnx:
        print("No MySQL connection provided, won't export")

    crashdb = jobresult_zip.extract(crashdb)

    def export_to_mysql(entry, mysql_cnx):
        """
        Export a crash into mysql.

        :param entry: row from crashdb as dictionary
        :param mysql_cnx: connection to MySQL
        """
        mysql_cursor = mysql_cnx.cursor()

        entry = defaultdict(lambda: None, entry)

        query = "INSERT INTO crashes (job_id, type, is_security_issue, is_crash, sample_path, backtrace, backtrace_hash, return_code) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        try:
            mysql_cursor.execute(
                query,
                (
                    jobid,
                    entry["type"],
                    entry["is_security_issue"],
                    entry["is_crash"],
                    entry["sample"],
                    entry["backtrace"],
                    entry["hash"],
                    entry["return_code"],
                ),
            )
        except mysql.connector.errors.IntegrityError as err:
            print("Integrity: {}".format(err))

        mysql_cnx.commit()
        mysql_cursor.close()

    def dict_factory(cursor, row):
        """
        Factory function for sqlite3 cursor.

        :return: each row as a dict having structure {"colname": value}
        """
        rowdict = {}
        for idx, col in enumerate(cursor.description):
            rowdict[col[0]] = row[idx]
        return rowdict

    cdbcon = sqlite3.connect(crashdb)
    cdbcon.row_factory = dict_factory
    cdbcur = cdbcon.cursor()
    result = cdbcur.execute("SELECT * FROM analysis")
    if not result:
        print("Crash database empty, nothing to export")
        return

    result = [dict(row) for row in result.fetchall()]

    # insert into mysql
    for analysis in result:
        # pull backtrace, if any, into dictionary
        print("Exporting entry: {}".format(analysis))

        analysis["hash"] = hashlib.md5(bytes(analysis["backtrace"], encoding="utf8")).hexdigest()
        analysis["is_crash"] = bool(analysis["is_crash"])
        analysis["is_security_issue"] = bool(analysis["is_security_issue"])
        # unused
        analysis["should_ignore"] = analysis["should_ignore"]

        if cnx:
            export_to_mysql(analysis, cnx)

    cdbcon.close()


def scan_job(jobdir, cnx):
    """
    Scan a single job directory.

    :param jobdir: absolute path to individual job directory
    :cnx: database connection, or None to skip export
    """
    # dejavu, i've just been in this place before
    if os.path.exists(jobdir + "/.scanned"):
        print("{} already scanned, skipping".format(jobdir))
        return

    print("Scanning job directory {}".format(jobdir))

    jobresult_file = jobdir + "/jobresults.zip"

    if os.path.exists(jobresult_file):
        print("Found jobresults.zip, checking for crashes")
        jobresult_zip = ZipFile(jobresult_file)
        crashdbs = list(filter(lambda x: "crashes.db" in x, jobresult_zip.namelist()))
        crashdb = crashdbs[0] if crashdbs else None
        if crashdb is not None:
            jobid = os.path.basename(jobdir.strip("/"))
            print("{}: Found crashes.db".format(jobid))
            process_jobresults(jobid, jobresult_zip, crashdb, cnx)
        else:
            print("No crashes.db, moving on")

        # lets not visit again
        Path(jobdir + "/.scanned").touch()
    else:
        print("No jobresults.zip, moving on")


def scan(directory, cnx):
    """
    Scan jobs directory for newly finished jobs. If a new job is found and its
    jobresults.zip contains a crash database, call process_jobresults to export
    crashes into MySQL.

    Once a job has been processed, we touch .scanned in the job directory in
    order to skip processing it on subsequent scans.

    :param directory: jobs directory to scan
    :param cnx: connection to MySQL database to export into
    """
    print("Scanning {}".format(directory))
    dirs = filter(
        os.path.isdir, map(lambda x: os.path.join(directory, x), os.listdir(directory)),
    )
    jobdirs = list(filter(lambda x: os.path.exists(x + "/job.yaml"), dirs))

    print("Job directories:")
    pprint.pprint(jobdirs)
    # when you're not performing your duties, do they keep you in a little box?
    for jobdir in jobdirs:
        scan_job(jobdir, cnx)


def lagopus_connect_db():
    """
    Connect to MySQL database and return result.

    :return: database connection
    """
    cnx = None

    try:
        connection_config = {
            k: DBCONF[k]
            for k in ["user", "password", "database", "host", "raise_on_warnings"]
        }
        cnx = mysql.connector.connect(**connection_config)
        print("Initialized database.")
    except mysql.connector.Error as err:
        print("Couldn't connect to MySQL: {}".format(err))

    return cnx


def lagopus_wait_connect_db(retry, wait):
    """
    Try to connect to database; if connection fails, retry after a time.

    :param retry: how many times to retry; -1 for infinity
    :param wait: how long to wait between tries, in seconds
    :return: database connection
    """
    cnx = lagopus_connect_db()
    while not cnx and retry != 0:
        if retry > 0:
            retry -= 1
        print("Failed to conenct to MySQL, retrying in {}s...".format(wait))
        time.sleep(wait)
        cnx = lagopus_connect_db()

    return cnx


CONNECT_RETRY_TIMER = 5
SCAN_TIMER = 15
JOBSDIR = "/jobs"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobsdir", type=str, help="where to look for job directories", default=JOBSDIR
    )
    parser.add_argument("--noexport", help="don't export to MySQL", action="store_true")
    parser.add_argument("--oneshot", help="do one scan and exit", action="store_true")

    args = parser.parse_args()

    cnx = (
        lagopus_wait_connect_db(-1, CONNECT_RETRY_TIMER) if not args.noexport else None
    )

    if args.oneshot:
        scan(args.jobsdir, cnx)
        if cnx:
            cnx.close()
        exit()

    while True:
        time.sleep(SCAN_TIMER)
        scan(args.jobsdir, cnx)

    cnx.close()

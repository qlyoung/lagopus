#!/usr/bin/env python3
# Scan job directory and update database

import os
import sqlite3
import time
import pprint
from pathlib import Path
from zipfile import ZipFile

import mysql.connector

DBCONF = {
    "user": "root",
    "password": "lagopus",
    "host": "localhost",
    "database": "lagopus",
    "raise_on_warnings": True,
    "tables": ["jobs", "crashes"],
}


def process_jobresults(jobname, crashdb, cnx):
    """
    Read crashes.db and export crash information into MySQL for use by the
    server.

    :param jobname: name of the job we are processing, same as the job
                    directory
    :param crashdb: path to sqlite3 crashes.db
    :param cnx: connection to MySQL database to export into
    """
    cursor = cnx.cursor()

    def dict_factory(cursor, row):
        """
        Factory function for MySQL cursor.

        :return: each row as a dict having structure {"colname": value}
        """
        rowdict = {}
        for idx, col in enumerate(cursor.description):
            rowdict[col[0]] = row[idx]
        return rowdict

    cdbcon = sqlite3.connect(crashdb)
    cdbcon.row_factory = dict_factory
    cdbcur = cdbcon.cursor()
    result = cdbcur.execute("SELECT * FROM Data")
    if not result:
        return

    result = [dict(row) for row in result.fetchall()]

    # k, insert into mysql
    for entry in result:
        if entry["Classification"] == "INVALID":
            continue
        query = "INSERT INTO crashes (job_name, type, exploitability, sample_path, backtrace, backtrace_hash) VALUES ('{}', '{}', '{}', '{}', '{}', '{}')".format(
            jobname,
            entry["Classification_Description"].split(" ")[0],
            entry["Classification"],
            entry["Sample"],
            "== No backtrace ==",
            entry["Hash"],
        )
        print("Executing: {}".format(query))
        try:
            cursor.execute(query)
        except mysql.connector.errors.IntegrityError as err:
            print("Integrity: {}".format(err))

    cnx.commit()
    cursor.close()
    cdbcon.close()


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
        # dejavu, i've just been in this place before
        if os.path.exists(jobdir + "/.scanned"):
            print("{} already scanned, skipping".format(jobdir))
            continue

        print("Scanning job directory {}".format(jobdir))

        jobid = jobdir
        jobresult_file = jobdir + "/jobresults.zip"

        if os.path.exists(jobresult_file):
            jobresult_zip = ZipFile(jobresult_file)
            crashdbs = list(
                filter(lambda x: "crashes.db" in x, jobresult_zip.namelist())
            )
            crashdb = crashdbs[0] if crashdbs else None
            if crashdb is not None:
                print("{}: Found crashes.db".format(jobid))
                crashdb = jobresult_zip.extract(crashdb)
                jobid = jobdir
                process_jobresults(jobid, crashdb, cnx)

            # lets not visit again
            Path(jobdir + "/.scanned").touch()


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


CONNECT_RETRY_TIMER = 5
SCAN_TIMER = 15

if __name__ == "__main__":
    cnx = lagopus_connect_db()
    while cnx is None:
        print(
            "Failed to conenct to MySQL, retrying in {}s...".format(CONNECT_RETRY_TIMER)
        )
        time.sleep(CONNECT_RETRY_TIMER)
        cnx = lagopus_connect_db()

    while True:
        time.sleep(SCAN_TIMER)
        scan("/jobs", cnx)

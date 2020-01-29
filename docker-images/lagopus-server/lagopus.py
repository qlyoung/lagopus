#!/usr/bin/env python3
#
# Copyright (C) Quentin Young 2020
# MIT License

# ----
# Kubernetes stuff
# ----
def lagopus_k8s_create_job():
    return {"Result": "Pass"}

def lagopus_k8s_get_jobs():
    return {"data": [["example-afl-1", "2", "200", "AFL", "2020-01-29"]]}

# ---
# Web
# ---
from flask import Flask
from flask import render_template
from flask import send_from_directory
app = Flask(__name__)

# --------
# JSON API
# --------
@app.route('/api/createjob')
def lagopus_api_create_job():
    return lagopus_k8s_create_job()

@app.route('/api/jobs')
def lagopus_api_get_jobs():
    return lagopus_k8s_get_jobs()

# -------------
# Web interface
# -------------
@app.route('/')
@app.route('/index.html')
def index():
    pagename = ""
    return render_template('index.html', pagename=pagename, jobcount=len(lagopus_api_get_jobs()))

@app.route('/jobs.html')
def jobs():
    pagename = "Jobs"
    return render_template('jobs.html', pagename=pagename)

@app.route('/crashes.html')
def crashes():
    pagename = "Crashes"
    return render_template('crashes.html', pagename=pagename)

@app.route('/targets.html')
def targets():
    pagename = "Targets"
    return render_template('targets.html', pagename=pagename)

@app.route('/404.html')
def fourohfour():
    pagename = "404"
    return render_template('404.html', pagename=pagename)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return send_from_directory('templates/', path)

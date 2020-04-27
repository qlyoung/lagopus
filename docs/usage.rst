.. _usage:

*****
Usage
*****

.. note::

   TODO: add screenshots


The Lagopus user interface is exposed as a web application. It is served on
port 80 at the IP address you configured during the :ref:`installation process
<installation>`. There are several components, each available on a different
part of the web interface.

The following pages are each linked in the sidebar of the web interface.

Dashboard
---------

The dashboard is the home page of the web interface. It has a list of jobs that
have been submitted to Lagopus. This list is sorted by recency and includes
both running and completed (or failed) jobs. Each job name in this list is
linked to the details page for that job, which contains monitoring and
statistics information, a summary of fuzzing results, and some controls
(presently just a "Kill" button to stop the job).

At the top of the page there are a few cards containing summary information
about the Lagopus deployment, including the current number of online nodes as
reported by Kubernetes and the number of running jobs.

To the right of the summary information is the "New Job" button that is used to
create new fuzzing jobs.

Jobs
----

Lagopus is designed around the concept of a ``Job``. A job is an individual
fuzzing session. Associated with a job are resources such as the containers
used to run it, the input zip defining it, its results, its location on the
storage volume, and so on.

Each Job has a page in the interface that provides all information about it.
This includes its current status, fine-grained statistics, progress information
for running jobs, a table of any discovered crashes, code coverage information
(not yet implemented), its resource limits, and what node it is running on.
This page is accessible by clicking on the name of the job from the Dashboard.

Creating Jobs
^^^^^^^^^^^^^
Lagopus accepts job definitions in a format very similar to `ClusterFuzz
<https://github.com/google/clusterfuzz>`_. It wants a zip archive with the
following structure:

::

   job.zip
   ├── corpus
   ├── provision.sh
   ├── target
   └── target.conf


Where:

- ``corpus`` is a directory containing a fuzzing corpus; it may be empty, but
  must be present
- ``provision.sh`` is a provisioning script used to setup the environment for
  the target (more on this below)
- ``target`` is your target binary
- ``target.conf`` is a config file for
  `afl-multicore <https://gitlab.com/rc0r/afl-utils>`_; this is only necessary
  when the job type is `afl`. libFuzzer jobs do not use this.


In addition to these files, you can include anything else you want in this zip
archive. This allows you to include e.g. config files or shared libraries
needed by the target.

The provision script allows you to customize the container used to run the job.
It will probably be necessary for most targets. This script is run before any
fuzzing takes place. Use it to install config files, packages, shared libraries
and anything else needed to run the target. Remember that the fuzzing container
is an Ubuntu 18.04 image, so you have access to all of Ubuntu's apt
repositories and can safely install any packages you need. Set it up however
you want; if you want to download some file, build some program from source,
delete system directories, whatever you want, feel free. Just don't delete
``/workdir``, ``/<jobname>``, or any of the fuzzing tools ;).


Crashes
-------

The main goal of any fuzzing system is to find bugs in target programs. When a
fuzzing job finds a crash, Lagopus automatically collects information about the
crash and imports it into its crash database. The contents of this database are
accessible via the Crashes page.

Each entry in the database contains the name of the job it is associated with
and the exit code of the target when run with the crashing input. Lagopus also
tries to describe the type of the crash by looking at the output of the program
when run with the crashing input. For example, Lagopus understands
ASAN/MSAN/TSAN/UBSAN output and will store the crash type reported by the
sanitizer (e.g. buffer overflow, race condition, etc.) in the ``Type`` field.

.. note::

   Crash analysis is performed with slightly modified code lifted from
   ClusterFuzz, so credit goes to Google for that piece.


The output of the program when run with the crashing input is available in the
``Backtrace`` column.

Each crash table entry also has a link to the fuzzing input that caused the
crash in the "Sample" column. Clicking this link downloads the input. This is
useful for local debugging.

.. note::

   Depending on the target and fuzzer, the backtrace may show a successful run
   and the sample provided for download may not reproduce the crash. This
   typically occurs with libFuzzer targets that accumulate state; the crash may
   only reproduce when 100 inputs are run in a particular sequence, building up
   the state necessary to create the error condition within the target. After
   finding a crashing input, Lagopus attempts to re-run the target with the
   input to generate a clean backtrace for analysis. If it doesn't cause a
   crash, Lagopus will fall back to scraping the job logs to get the backtrace,
   if available. When this happens, the exit code is logged as 101.

If you want to see crashes only for a particular job, go to that job's page and
click the "Crashes" tab.


API
---

Lagopus exposes an HTTP REST API. The web interface controls Lagopus solely
through this API to ensure that it stays up to date and covers all public
functionality. The ``API`` link in the sidebar brings up Swagger-generated API
docs. Each endpoint has a documentation blurb associated with it that explains
the purpose and usage of the endpoint.

The API provides programmatic access to any task achievable via the web
interface.

Because Lagopus itself has no facilities for recurring jobs, CI integration,
email reporting, and other desirable features, the goal of the API is to allow
as much flexibility and extensibility as possible. For instance, if you want to
kick off a fuzz job after each build of your project in CI, you can simply
build a job zip as one of your CI artifacts and POST it to the job creation
endpoint.

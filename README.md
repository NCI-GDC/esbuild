# esbuild

Repository for building the GDC Elasticsearch indices.

[![Build Status](https://travis-ci.com/NCI-GDC/esbuild.svg?token=LApTVTN34FyXpxo5zU44&branch=develop)](https://magnum.travis-ci.com/NCI-GDC/esbuild)

- [Running](#running)
- [Technologies](#technologies)
- [Installation](#installation)
- [Tests](#tests)
- [Development](#development)
- [Contributing](#contributing)
- [Production](#production)

# Running

```bash
export PG_HOST=<REPLACE_ME>  # PostgreSQL hostname
export PG_USER=<REPLACE_ME>  # PostgreSQL user
export PG_PASS=<REPLACE_ME>  # PostgreSQL password
export PG_NAME=<REPLACE_ME>  # PostgreSQL database name

export ELASTICSEARCH_HOST=<REPLACE_ME>  # Elasticsearch hostname
export ES_USER=<REPLACE_ME>  # Elasticsearch user
export ES_PASSWORD=<REPLACE_ME>  # Elasticsearch password

python bin/build_graph_index.py
```

While running, we have a temporary fix in that allows the proper
released states to be set per program/project for active vs legacy.

This is a temporary solution that automates the setting of these
flags. We have a PR in that fixes this at the root level, and when
that is done, this code should be removed.

This code is automatically run from the esbuild wrapper, so no 
extra execution is necessary.

In the meantime, the format is this:
```ACTIVE: # Which build is running, either ACTIVE or LEGACY
    PROGRAMS: # The set of programs that are to be altered
        CCLE: # The program name, all in caps
            PROJECTS: '*' # Wildcard which means "do every project", this
                          # should never be a list, just a single entry
            RELEASED: False # The state to set released to for these programs
        TARGET:
            PROJECTS: # If wildcard isn't used, a list of project names
                      # is expected, matching exactly the code in psql
                      # This should always be a list, so dashes even
                      # if there's only one project name
                - ALL-P1
                - ALL-P2
            RELEASED: False
```
This data is checked in in a yaml file (project-program-release.yaml) in the 
bin directory of esbuild. It is deployed and can be edited on the esbuild 
machine to change as need be.

# Installation

Before continuing you must have the following programs installed:

- [Python 2.7+](http://python.org/)

## Pip

Project dependencies are managed using
[PIP](https://pip.readthedocs.org/en/latest/). You can install
dependencies via

```
> pip install -r requirements.txt
```

And optionally any dev requirements via

```
> pip install -r dev-requirements.txt
```

### Project Dependencies

If you are building to a local Elasticsearch installation, you will
need to install it manually.  On OSX you can install Elasticsearch via
`brew install elasticsearch`.

# Tests

Tests can be found in `tests/` and can be run via [pytest](http://pytest.org/latest/getting-started.html).

# Production

This library was written with the intention of deploying via SaltStack and [tungsten](https://github.com/NCI-GDC/tungsten/tree/develop/tungsten).

# Contributing

Read how to contribute [here](https://github.com/NCI-GDC/esbuild/blob/master/contributing.md).

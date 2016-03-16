# esbuild

Repository for building the GDC Elasticsearch indices.

[![Build Status](TODO)](https://magnum.travis-ci.com/NCI-GDC/esbuild)

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

export ES_HOST=<REPLACE_ME>  # Elasticsearch hostname
export ES_USER=<REPLACE_ME>  # Elasticsearch user
export ES_PASS=<REPLACE_ME>  # Elasticsearch password
export ES_INDEX=<REPLACE_ME> # Elasticsearch alias name

python bin/build_graph_index.py
```

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

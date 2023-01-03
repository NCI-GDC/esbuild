# esbuild

Repository for building the GDC Elasticsearch indices.

[![Build Status](https://travis-ci.com/NCI-GDC/esbuild.svg?token=LApTVTN34FyXpxo5zU44&branch=develop)](https://magnum.travis-ci.com/NCI-GDC/esbuild)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Running](#running)
  - [build_graph_index.py](#build_graph_indexpy)
  - [compare_indices.py](#compare_indicespy)
    - [flags](#flags)
      - [`--test-type`](#--test-type)
      - [`--true-index` and `--test-index`](#--true-index-and---test-index)
    - [Usage](#usage)
- [Architecture](#architecture)
  - [Build and Upload Process](#build-and-upload-process)
  - [Builders and Mappers](#builders-and-mappers)
    - [Mappers](#mappers)
- [Trouble shooting](#trouble-shooting)
- [Installation](#installation)
  - [Pip](#pip)
    - [Project Dependencies](#project-dependencies)
- [Development](#development)
  - [Tests](#tests)
  - [Setup pre-commit hook to check for secrets](#setup-pre-commit-hook-to-check-for-secrets)
- [Production](#production)
- [Contributing](#contributing)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Running

## build_graph_index.py

```bash
export PG_HOST=<REPLACE_ME>  # PostgreSQL hostname
export PG_USER=<REPLACE_ME>  # PostgreSQL user
export PG_PASS=<REPLACE_ME>  # PostgreSQL password
export PG_NAME=<REPLACE_ME>  # PostgreSQL database name

export ES_HOST=<REPLACE_ME>  # Elasticsearch hostname
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

## compare_indices.py

This is a script used to compare 2 indices. It can be used to see the changes between
new indices and old indices. An output file with name `counts_<index_name>_vs_<another_index_name>.json`
or `compared_<index_name>_vs_<another_index_name>.json` will be generated.

### flags

#### `--test-type`

Choose between `compare-counts` and `full-compare`

* `compare-counts` will show the count difference for indices.
* `full-compare` will show detailed doc difference for indices.

#### `--true-index` and `--test-index`

Those flags are used to provide names for indices to compare.


### Usage

```bash
compare_indices.py --true-index dr33_active_merged_file --test_index dr33_active_merged_v2_file --test-type compare_counts
```


=======
# Architecture

## Build and Upload Process

The JSON index is built in the following steps:

0. Cache the graph from the database in memory
0. Filter out nodes from the graph that should be excluded
0. Cache commonly used information, e.g. case to file relationships
0. Visit each case, producing a case doc and all annotation and file docs for that case
0. Merge file docs together (to allow for multiple cases in a file doc)
0. Produce project summary docs
0. Validate produced docs

The index is uploaded to elasticsearch in the following steps:

0. Create a new index in naming scheme
0. Upload each doc type to index
0. On success, update the alias to point to new index
0. Cleanup/close old indexes

## Builders and Mappers

Esbuild consists of a `builder` and a `mapper` for each index it
produces (i.e. Legacy and Active).

* The `mapper` produces the Elasticsearch mapping and contains basic traversals
* The `builder` produces JSON documents using the `mapper`

Most of the business logic for building indices is contained in the
`graph.common.builder.GraphIndexBuilder` class, which is inherited by
`graph.common.builder.ActiveGraphIndexBuilder` and
`graph.common.builder.LegacyGraphIndexBuilder` to build the Active and
Legacy indices respectively.

Builders exclude nodes that shouldn't be in the index (and therefore
public) based during the filtering step in the `is_node_indexed()`
function.

Each builder has a set of class variables that alter build behavior,
including but not limited to `mapper`, `file_mapping`,
`case_to_file_paths`, `unindexed_by_property`, `hidden_properties`.
Those that are required to be overloaded are listed in
`required_attrs`.

Each `case` document contains all of the files derived from it.  Each
`file` document in that case document contain a _pruned_ version of
the parent `case` document that contains only the direct ancestors of
the file, i.e. only those found along all paths from the file to the
case.  This re-nesting is done to allow additional filtering in
Elasticsearch.

Because file documents are produced by visiting a single case, the
traversal from that case to each file will only contain one case.
This means that file documents must be merged together in order to
contain all the cases they are derived from. This is done as follows:

0. for each file doc from `denormalize_case() -> (case_docs,
   file_docs, annotation_docs)`
0. if there is an existing doc for this file and the newly produced
   document contains a subtree for a case that is not in the old doc,
   then append the case subtree from the new doc to that of the old
   doc.

### Mappers

The mappers (see the `graph.common.mappings` module) produce the
_mapping_ (or schema) for Elasticsearch.  They are also setup in
classes for code re-use, allowing easy extensibility of the Active and
Legacy mappers which inherit functionality from the common mapper.
The mappers have three main functions to produce mappings:
`get_{project,case,annotation,file}_es_mapping`.

The properties of each Entity (Node class) are dynamically added to
the mapping based on the GDC Dictionary.

The traversal tree in the legacy mappings are static.

The traversal tree in the active mappings are a dynamic extension of
the static legacy mappings.

# Trouble shooting

Included in the module are two `mimic` builders, one for legacy and
active.  These can be used to test functionality against nodes,
e.g. testing `builder.is_node_indexed(node)` to troubleshoot nodes
that are not showing up in the index.

```python
>>> from esbuild.graph.active.mimic import ActiveMimic
>>> from gdcdatamodel.models import Case
>>> mimic = ActiveMimic(None)
>>> mimic.is_node_indexed(Case())
[...][graph_index][   INFO] not indexed (unsubmitted state: <Case(None)>): None
False
```

# Installation

Before continuing you must have the following programs installed:

- [Python 2.7+](http://python.org/)
- [graphviz](http://www.graphviz.org/) for optional test suite data visualization

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

# Development

## Tests

Tests can be found in `tests/` and can be run
via [pytest](http://pytest.org/latest/getting-started.html).

Or you can use [tox](https://tox.readthedocs.io/en/latest/) to run tests:

```
pip install tox
tox
```

The test suite data is visualized in a PDF
using [graphviz](http://www.graphviz.org/) if you have installed
whenever the tests are run.

### Parallel testing

We are now able to run the tests in parallel, with `indexd_test_utils2`,
`pytest-postgresql`, `pytest-elasticsearch` and `pytest-xdist`.
To start test in parallel, run with the following command:
```bash
pytest tests -n auto
```

If your elasticsearch is not installed in default location or your are using opensearch,
set the following env:
```bash
ES_EXECUTABLE=/opt/homebrew/opt/opensearch/bin/opensearch
```

If you are using mac, you also need to set:
```bash
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

## Setup pre-commit hook to check for secrets

We use [pre-commit](https://pre-commit.com/) to setup pre-commit hooks for this repo.
We use [detect-secrets](https://github.com/Yelp/detect-secrets) to search for secrets being committed into the repo.

To install the pre-commit hook, run
```
pre-commit install
```

To update the .secrets.baseline file run
```
detect-secrets scan --update .secrets.baseline
```

`.secrets.baseline` contains all the string that were caught by detect-secrets but are not stored in plain text. Audit the baseline to view the secrets .

```
detect-secrets audit .secrets.baseline
```

# Production

This library was written with the intention of deploying via SaltStack
and
[tungsten](https://github.com/NCI-GDC/tungsten/tree/develop/tungsten).

# Contributing

Read how to
contribute
[here](https://github.com/NCI-GDC/esbuild/blob/master/contributing.md).

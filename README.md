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

Esbuild consistes of a `builder` and a `mapper` for each index it
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

# Tests

Tests can be found in `tests/` and can be run
via [pytest](http://pytest.org/latest/getting-started.html).

The test suite data is visualized in a PDF
using [graphviz](http://www.graphviz.org/) if you have installed
whenever the tests are run.

# Production

This library was written with the intention of deploying via SaltStack
and
[tungsten](https://github.com/NCI-GDC/tungsten/tree/develop/tungsten).

# Contributing

Read how to
contribute
[here](https://github.com/NCI-GDC/esbuild/blob/master/contributing.md).

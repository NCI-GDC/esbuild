from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="esbuild",
    description="Repository for building the GDC Elasticsearch indices.",
    license="Apache",
    author="NCI GDC",
    author_email="gdc_dev_questions-aaaaae2lhsbell56tlvh3upgoq@cdis.slack.com",
    url="https://github.com/NCI-GDC/esbuild",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
    ],
    packages=find_packages(exclude=("tests",)),
    install_requires=[
        "addict",
        "cdislogging~=1.0",
        "datadog~=0.32",
        "deepdiff~=4.0",  # required by compare_indices
        "dictdiffer~=0.8.0",
        "elasticsearch~=7.6",
        "networkx",
        "progressbar2>=2.0,<4",
        "python-dotenv~=0.10.3",
        "requests~=2.7",
        "SQLAlchemy==1.3.3",
        "psqlgraph @ git+ssh://git@github.com/NCI-GDC/psqlgraph.git@4.0.2#egg=psqlgraph",
        "gdcdictionary @ git+ssh://git@github.com/NCI-GDC/gdcdictionary.git@2.4.0#egg=gdcdictionary",
        "gdcdatamodel @ git+ssh://git@github.com/NCI-GDC/gdcdatamodel.git@4.1.1#egg=gdcdatamodel",
        "gdc_ng_models @ git+ssh://git@github.com/NCI-GDC/gdc-ng-models.git@1.5.2#egg=gdc_ng_models",
        "indexclient @ git+ssh://git@github.com/NCI-GDC/indexclient.git@2.3.7#egg=indexclient",
        "queueclient @ git+ssh://git@github.com/NCI-GDC/queueclient.git@1.2.0#egg=queueclient",
        "gdcmodels @ git+https://github.com/NCI-GDC/gdc-models.git@4.0.0#egg=gdcmodels",
        "normalizer @ git+ssh://git@github.com/NCI-GDC/normalizer.git@4.0.0#egg=normalizer",
    ],
    extras_require={
        "dev": [
            "jmespath~=0.10",
            "mock~=3.0",
            "more-itertools==8.14.0",
            "pytest",
            "pytest-cov~=2.8",
            "python-dateutil<2.8.1,>=2.1",
            "pytest-elasticsearch",
            "pytest-postgresql",  # this should not be needed
            "indexdmodels @ git+ssh://git@github.com/NCI-GDC/indexdmodels.git@0.2.0#egg=indexdmodels",  # this should not be needed
            "indexd @ git+ssh://git@github.com/NCI-GDC/indexd.git@2.13.0#egg=indexd",
            "indexclient[pytest_indexd] @ git+ssh://git@github.com/NCI-GDC/indexclient.git@2.3.7#egg=indexclient[pytest_indexd]",
        ]
    },
    scripts=[
        "bin/esbuild-cli",
        "bin/compare_indices.py",
        "bin/master.py",
        "bin/minion.py",
    ],
    include_package_data=True,
)

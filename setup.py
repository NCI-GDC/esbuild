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
        "datadog~=0.32",
        "deepdiff~=6.5.0",  # required by compare_indices
        "dictdiffer~=0.8.0",
        "elasticsearch~=7.6",
        "more-itertools==8.14.0",
        "networkx",
        "progressbar2>=2.0,<4",
        "python-dotenv~=0.10.3",
        "python-json-logger~=2.0",
        "requests~=2.7",
        "SQLAlchemy<1.4",
        "psqlgraph",
        "gdcdictionary==3.0.3",
        "gdcdatamodel2==3.0.3",
        "gdc_ng_models>1.6.0",
        "indexclient",
        "queueclient",
        "gdcmodels",
        "normalizer",
    ],
    extras_require={
        "dev": [
            "jmespath~=0.10",
            "mock~=3.0",
            "pytest>=7.0.0",  # older version will not work with pytest-elasticsearch 4.0.1
            "pytest-cov~=2.8",
            "python-dateutil<2.8.1,>=2.1",
            "pytest-elasticsearch",
            "pytest-postgresql",  # this should not be needed
            "graphviz~=0.19.1",  # this should not be needed
            "gdcdatamodel2[visualization]",
            "indexdmodels",  # this should not be needed
            "indexd",
            "indexclient[pytest_indexd]",
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

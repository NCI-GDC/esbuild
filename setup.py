from setuptools import setup, find_packages

setup(
    name="esbuild",
    version="1.5.1",
    description="Repository for building the GDC Elasticsearch indices.",
    license="Apache",
    packages=find_packages(exclude=('tests',)),
    install_requires=[
        # Tests for Python35 not run on >=2.2.0 anymore
        "addict<2.2.0",
        "cdislogging~=1.0",
        "datadog~=0.32",
        "dictdiffer~=0.8.0",
        "elasticsearch~=7.6",
        # gdcdatamodel needs future
        "future~=0.18.2",
        # Last version to support Python35 is 2.4
        "networkx<=2.4",
        "progressbar2>=2.0,<4",
        "python-dotenv~=0.10.3",
        "requests~=2.7",
        "six~=1.12",
        "SQLAlchemy==1.3.3",
        "psqlgraph @ git+ssh://git@github.com/NCI-GDC/psqlgraph.git@3.0.0#egg=psqlgraph",
        "gdcdictionary @ git+ssh://git@github.com/NCI-GDC/gdcdictionary.git@2.2.0#egg=gdcdictionary",
        "gdcdatamodel @ git+ssh://git@github.com/NCI-GDC/gdcdatamodel.git@3.0.0#egg=gdcdatamodel",
        "gdc_ng_models @ git+ssh://git@github.com/NCI-GDC/gdc-ng-models.git@1.4.0#egg=gdc_ng_models",
        "indexclient @ git+ssh://git@github.com/NCI-GDC/indexclient.git@2.0.0#egg=indexclient",
        "queueclient @ git+ssh://git@github.com/NCI-GDC/queueclient.git@1.2.0#egg=queueclient",
        "gdcmodels @ git+ssh://git@github.com/NCI-GDC/gdc-models.git@2.4.0#egg=gdcmodels",
        "normalizer @ git+ssh://git@github.com/NCI-GDC/normalizer.git@2.0.4#egg=normalizer",
    ],
    scripts=[
        'bin/esbuild-cli',
    ],
)

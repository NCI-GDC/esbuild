from setuptools import setup, find_packages

setup(
    name="esbuild",
    version="1.5.1",
    description="Repository for building the GDC Elasticsearch indices.",
    license="Apache",
    packages=find_packages(exclude=('tests',)),
    scripts=[
        'bin/esbuild-cli',
        'bin/build_download_stats_index.py',
    ]
)

#!/usr/bin/env python

from esbuild.reports.download_report import DownloadStatsIndexBuilder


def main():
    builder = DownloadStatsIndexBuilder()
    builder.go()


if __name__ == "__main__":
    main()

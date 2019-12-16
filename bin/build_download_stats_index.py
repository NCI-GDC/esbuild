#!/usr/bin/env python3

from esbuild.reports.download_report import DownloadStatsIndexBuilder


def main():
    builder = DownloadStatsIndexBuilder()
    builder.go()


if __name__ == "__main__":
    main()

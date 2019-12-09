#!/usr/bin/env python

from esbuild.export.s3_upload import export_to_gzip_and_upload_to_s3


def main():
    export_to_gzip_and_upload_to_s3()


if __name__ == "__main__":
    main()

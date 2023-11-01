#!/usr/bin/env python3
import argparse
import collections
import json
import multiprocessing
from typing import Iterator, NamedTuple, Optional

import cdislogging
import deepdiff
import elasticsearch
import elasticsearch.helpers
import more_itertools

import esbuild.utils

IGNORE_KEYS = (
    "updated_datetime",  # This might change when node is touched
    "portion_id",
    "analyte_id",  # These are randomly generated each esbuild run
    "file_state",
    "state",
    "releasable",  # System fields
)


class DocPair(NamedTuple):
    true_doc: dict
    test_doc: dict


def diff_func(doc_pair: DocPair) -> list:
    return list(
        deepdiff.DeepDiff(
            doc_pair.test_doc["_source"],
            doc_pair.true_doc["_source"],
            ignore_order=True,
        )
    )


class DataTester:
    """Esbuild data quality tests."""

    def __init__(self):
        self.parser = argparse.ArgumentParser(description="Parses tester arguments")
        # Adds extra args
        self.add_args()

        self.args = self.parser.parse_args()
        self.index_suffixes = ["case", "file", "annotation", "project"]

        log_level = "debug" if self.args.debug else "info"
        self.log = cdislogging.get_logger("DataTester", log_level=log_level)
        self.es_worker = ESWorker(self.args.page_size, log_level=log_level)

    def add_args(self) -> None:
        """Add extra arguments to a parser."""
        self.parser.add_argument(
            "--true-index", required=True, help="Reference esbuild index base name."
        )
        self.parser.add_argument(
            "--test-index", required=True, help="Test esbuild index base name."
        )
        self.parser.add_argument(
            "--test-type",
            required=True,
            choices=["compare_counts", "full_compare"],
            help="Choose test to run",
        )
        self.parser.add_argument(
            "--page-size",
            default=1000,
            type=int,
            help="Page size for elasticsearch query scans.",
        )
        self.parser.add_argument(
            "--debug",
            action="store_true",
            help="debug logging",
        )

    def run(self) -> None:
        test_type = self.args.test_type
        self.log.info(f"Running {test_type.upper()} test")
        getattr(self, test_type)()

    def compare_counts(self) -> bool:
        """Extract counts from test and true indices and compares them."""
        # Get counts
        test_counts = self.get_counts(self.args.test_index)
        true_counts = self.get_counts(self.args.true_index)
        report = {
            "test_counts": {
                "annotation": test_counts["annotation"]["counts"]["total"],
                "case": test_counts["case"]["counts"]["total"],
                "file": test_counts["file"]["counts"]["total"],
                "project": test_counts["project"]["counts"]["total"],
            },
            "true_counts": {
                "annotation": true_counts["annotation"]["counts"]["total"],
                "case": true_counts["case"]["counts"]["total"],
                "file": true_counts["file"]["counts"]["total"],
                "project": true_counts["project"]["counts"]["total"],
            },
        }

        mismatches = deepdiff.DeepDiff(true_counts, test_counts)
        if mismatches:
            self.log.warning("Mismatches found:")
            self.log.warning(mismatches)

        # Write counts to file
        report_filename = (
            f"counts_{self.args.true_index}_vs_{self.args.test_index}.json"
        )
        with open(report_filename, "w") as f:
            json.dump(report, f, indent=2)

        return mismatches == {}

    def full_compare(self) -> None:
        """Iterate over all documents and compares."""
        # Get document counts
        true_counts = self.get_counts(self.args.true_index)
        sizes = {k: v["counts"]["total"] for k, v in true_counts.items()}

        self.log.info(
            f"Running full comparison of {self.args.true_index} and {self.args.test_index} indices:"
        )
        # TODO: incorporate functionality in
        # if IGNORE_KEYS:
        #    self.log.warning("Ignoring {} fields".format(", ".join(IGNORE_KEYS)))

        # For each index name in active, iterate over entire index and compare
        result = {i: {} for i in self.index_suffixes}
        for index_suffix in self.index_suffixes:
            doc_count = 0
            doc_pairs = []
            current_true_index = f"{self.args.true_index}_{index_suffix}"
            current_test_index = f"{self.args.test_index}_{index_suffix}"

            self.log.info(f"Comparing {index_suffix}s")

            for true_doc_chunk in more_itertools.chunked(
                self.es_worker.get_es_iterator(current_true_index),
                self.args.page_size,
            ):
                doc_count += len(true_doc_chunk)
                self.log.debug(f"progress: {doc_count}/{sizes[index_suffix]}")
                true_docs = {d["_id"]: d for d in true_doc_chunk}
                test_docs = {
                    d["_id"]: d
                    for d in self.es_worker.get_es_iterator(
                        current_test_index,
                        query={"query": {"ids": {"values": list(true_docs.keys())}}},
                    )
                }

                for true_did, true_doc in true_docs.items():
                    if true_did not in test_docs:
                        result[index_suffix][true_did] = "Missing"
                        continue

                    doc_pairs.append(DocPair(true_doc, test_docs[true_did]))

                with multiprocessing.Pool() as p:
                    for diff in p.map(diff_func, doc_pairs):
                        if diff:
                            result[index_suffix][true_did] = diff

            self.log.info(f"Done working on {index_suffix}.")

        for index_suffix, res in result.items():
            self.log.info(f"Diff in {index_suffix}: {not all(res.values())}")

        report_filename = (
            f"compared_{self.args.true_index}_vs_{self.args.test_index}.json"
        )

        with open(report_filename, "w") as f:
            json.dump(result, f)

    def get_counts(self, base_index_name: str) -> dict:
        """Extract counts from :es_worker's ES cluster :base_index_name index."""
        simple_test_cases = {
            "project": [
                "primary_site",
                "disease_type",
            ],
            "case": [
                "primary_site",
                "disease_type",
                "project.project_id",
                "project.disease_type",
                "project.primary_site",
            ],
            "file": [
                "uploaded_datetime",
                "project_id",
            ],
            "annotation": [
                "annotation_id",
                "project_id",
            ],
        }

        array_test_cases = {
            "case": [
                "aliquot_ids",
                "diagnoses",
                "files",
                "project.disease_type",
                "project.primary_site",
                "sample_ids",
                "samples",
                "samples.portions",
                "samples.portions.analytes",
                "samples.portions.analytes.aliquots",
                "submitter_aliquot_ids",
                "submitter_sample_ids",
                "summary.data_categories",
                "summary.experimental_strategies",
            ],
            "file": [
                "acl",
                "analysis.input_files",
                "associated_entities",
                "cases",
                "cases.diagnoses",
                "cases.diagnoses.treatments",
                "cases.exposures",
                "cases.samples",
                "cases.samples.portions",
                "cases.samples.portions.analytes",
                "cases.samples.portions.analytes.aliquots",
                "cases.samples.portions.slides",
                "downstream_analyses",
                "downstream_analyses.output_files",
            ],
            "project": [
                "disease_type",
                "primary_site",
                "summary.data_categories",
                "summary.experimental_strategies",
            ],
            "annotation": [
                "project.disease_type",
                "project.primary_site",
            ],
        }

        document_counts = collections.defaultdict(dict)

        # Simple count test cases
        for index_suffix, field_list in simple_test_cases.items():
            index_name = f"{base_index_name}_{index_suffix}"
            simple_counts = self.es_worker.get_simple_counts(index_name, field_list)
            document_counts[index_suffix]["counts"] = simple_counts

        # Sum of lengths of array field test cases
        for index_suffix, path_list in array_test_cases.items():
            index_name = f"{base_index_name}_{index_suffix}"
            list_size_sums = self.es_worker.get_list_size_sums(index_name, path_list)
            document_counts[index_suffix]["list_size_sums"] = list_size_sums

        return dict(document_counts)


class ESWorker:
    """Works with elasticsearch indices, extracts data and counts."""

    def __init__(self, page_size: int, log_level: str):
        self.es = esbuild.utils.get_elasticsearch_client()
        self._page_size = page_size
        self.log = cdislogging.get_logger("ESWorker", log_level=log_level)

    def get_simple_counts(
        self, index_name: str, field_list: Optional[dict] = None
    ) -> dict[str, int]:
        """Extract field counts from es index."""
        if not field_list:
            field_list = []
        total_docs = self.es.count(index=index_name, body={})["count"]

        counts = {"total": total_docs}
        for field in field_list:
            field_exists_query = {"query": {"exists": {"field": field}}}
            field_count = self.es.search(index=index_name, body=field_exists_query)[
                "hits"
            ]["total"]
            counts[field] = field_count

        return counts

    def get_list_size_sums(self, index_name: str, path_list: dict) -> dict:
        """Aggregate sum of lengths of array fields in :path_list in index."""
        list_size_sums = {}
        for path in path_list:
            list_size_sum_query = {
                "size": 0,
                "aggs": {
                    "outer_agg": {
                        "nested": {
                            "path": path,
                        },
                        "aggs": {
                            "inner_agg": {
                                "top_hits": {
                                    "from": 0,
                                    "size": 1,
                                }
                            }
                        },
                    }
                },
            }

            size_sum = self.es.search(index=index_name, body=list_size_sum_query)[
                "aggregations"
            ]["outer_agg"]["doc_count"]
            list_size_sums[path] = size_sum
        return list_size_sums

    def get_es_iterator(
        self, index_name: str, query: Optional[dict] = None
    ) -> Iterator[dict]:
        """Return full index document iterator."""
        if not query:
            query = {"query": {"match_all": {}}}

        yield from elasticsearch.helpers.scan(
            self.es,
            index=index_name,
            scroll="20m",
            size=self._page_size,
            query=query,
        )


if __name__ == "__main__":
    tester = DataTester()
    tester.run()

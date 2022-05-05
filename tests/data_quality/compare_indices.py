import argparse
import logging
import json
from cdislogging import get_logger
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan
from pprint import pformat
from deepdiff import DeepDiff
from dictdiffer import diff

log = get_logger('compare_indices')
log.setLevel(level=logging.INFO)

IGNORE_KEYS = (
    'updated_datetime',  # This might change when node is touched
    'portion_id', 'analyte_id',  # These are randomly generated each esbuild run
    'file_state', 'state', 'releasable',  # System fields
)


class DataTester:
    """ Esbuild data quality tests """

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            description='Parses tester arguments')
        # Adds extra args
        self.parser = self.add_args(self.parser)

        self.es_worker = ESWorker(self.parser)

        self.args = self.parser.parse_args()
        self.doc_types = ['case', 'file', 'annotation', 'project']

    def add_args(self, parser):
        """ Add extra arguments to a parser """
        parser.add_argument('--true-index', required=True,
                            help='Choose reference esbuild index.')
        parser.add_argument('--test-index', required=True,
                            help='Choose esbuild index of interest.')
        parser.add_argument('--test-type', required=True,
                            choices=['compare_counts', 'full_compare'],
                            help='Choose test to run')
        return parser

    def run(self):
        test_type = self.args.test_type
        log.info('\n\nRunning {} test'.format(test_type.upper()))
        getattr(self, test_type)()

    def compare_counts(self):
        """ Extracts counts from test and true indices and compares them """

        # Get counts
        test_counts = self.get_counts(self.es_worker, self.args.test_index)
        true_counts = self.get_counts(self.es_worker, self.args.true_index)

        # Write counts to file
        report_file = 'counts_{}_vs_{}.json'.format(self.args.true_index,
                                                    self.args.test_index)
        with open(report_file, 'w') as f:
            f.write('\n\n[Comparing counts]\n')
            f.write('_' * 80 + '\n')
            f.write('\n[{}:{}]\n[{}] counts'.format(self.args.es_host,
                                                    self.args.es_port,
                                                    self.args.true_index))
            f.write(pformat(true_counts) + '\n')
            f.write('_' * 80 + '\n')
            # Test index counts
            f.write('\n[{}:{}]\n[{}] counts\n'.format(self.args.es_host,
                                                      self.args.es_port,
                                                      self.args.test_index))
            f.write(pformat(test_counts) + '\n')
            f.write('_' * 80 + '\n')
            f.write('Mismatches found:\n')
            mismatches = DeepDiff(true_counts, test_counts)
            f.write(pformat(mismatches) + '\n')
            f.write('_' * 80 + '\n')

        return mismatches == {}

    def full_compare(self):
        """ Iterates over all documents and compares """
        # Get document counts
        true_counts = self.get_counts(self.es_worker, self.args.true_index)
        sizes = {k: v['counts']['total'] for k, v in true_counts.items()}

        log.info(
            'Running full comparison of {} and {} indices:'.format(
                self.args.true_index, self.args.test_index
            )
        )
        if IGNORE_KEYS:
            log.warning('Ignoring {} fields'.format(', '.join(IGNORE_KEYS)))

        # For each doctype, iterate over entire index and compare
        result = {d: {} for d in self.doc_types}
        for doc_type in self.doc_types:
            log.info('Comparing {}s:'.format(doc_type))
            true_docs = self.es_worker.get_es_iterator(self.es_worker.es,
                                                       self.args.true_index,
                                                       doc_type)
            doc_count = 0
            for doc in true_docs:
                doc_count += 1
                try:
                    test_doc = self.es_worker.es.get(index=self.args.test_index,
                                                     doc_type=doc_type, id=doc['_id'])
                except:
                    log.warning('{} {} was not found in {}, skipping'
                                .format(doc_type, doc['_id'], self.args.test_index))
                    continue

                # Check if true document fully matches test document
                diffs = diff(doc['_source'], test_doc['_source'])
                diffs = [
                    d for d in diffs
                    if (d[1] not in set(IGNORE_KEYS) and
                        not d[1].endswith(IGNORE_KEYS))
                ]
                is_correct = len(diffs) == 0

                result[doc_type][doc['_id']] = is_correct
                if doc_count % 100 == 0:
                    log.info('progress: {}/{}'.format(doc_count, sizes[doc_type]))

        report_file = 'compared_{}_vs_{}.json'.format(self.args.true_index,
                                                      self.args.test_index)
        with open(report_file, 'w') as f:
            for doc_type, res in result.items():
                f.write('{}: {}\n'.format(doc_type, all(res.values())))
            f.write(json.dumps(result))

    def get_counts(self, es_worker, index_name):
        """ Extracts counts from :es_worker's ES cluster :index_name index"""

        simple_test_cases = [
            ('project',
                [
                    'primary_site',
                    'disease_type',
                ]
             ),
            ('case',
                [
                    'primary_site',
                    'disease_type',
                    'project.project_id',
                    'project.disease_type',
                    'project.primary_site',
                ]
             ),
            ('file',
                [
                    'uploaded_datetime',
                    'project_id',
                ]
             ),
            ('annotation',
                [
                    'annotation_id',
                    'project_id',
                ]
             ),
        ]

        array_test_cases = [
            ('case',
                [
                    'aliquot_ids',
                    'diagnoses',
                    'files',
                    'project.disease_type',
                    'project.primary_site',
                    'sample_ids',
                    'samples',
                    'samples.portions',
                    'samples.portions.analytes',
                    'samples.portions.analytes.aliquots',
                    'submitter_aliquot_ids',
                    'submitter_sample_ids',
                    'summary.data_categories',
                    'summary.experimental_strategies',
                ]
             ),
            ('file',
                [
                    'acl',
                    'analysis.input_files',
                    'associated_entities',
                    'cases',
                    'cases.diagnoses',
                    'cases.diagnoses.treatments',
                    'cases.exposures',
                    'cases.samples',
                    'cases.samples.portions',
                    'cases.samples.portions.analytes',
                    'cases.samples.portions.analytes.aliquots',
                    'cases.samples.portions.slides',
                    'downstream_analyses',
                    'downstream_analyses.output_files',
                ]
             ),
            ('project',
                [
                    'disease_type',
                    'primary_site',
                    'summary.data_categories',
                    'summary.experimental_strategies',
                ]
             ),
            ('annotation',
                [
                    'project.disease_type',
                    'project.primary_site',
                ]
            ),
        ]

        document_counts = {_: {} for _ in self.doc_types}

        # Simple count test cases
        for test_case in simple_test_cases:
            doc_type, field_list = test_case
            simple_counts = es_worker.get_simple_counts(es_worker.es, index_name,
                                                        doc_type, field_list)
            document_counts[doc_type]['counts'] = simple_counts

        # Sum of lengths of array field test cases
        for test_case in array_test_cases:
            doc_type, path_list = test_case
            list_size_sums = es_worker.get_list_size_sums(es_worker.es, index_name,
                                                          doc_type, path_list)
            document_counts[doc_type]['list_size_sums'] = list_size_sums

        return document_counts


class ESWorker:
    """ Works with elasticsearch indices, extracts data and counts """

    def __init__(self, parser=None):
        if not parser:
            self.parser = argparse.ArgumentParser(
                description='Parses elasticsearch arguments')
        else:
            self.parser = parser

        self.parser = self.add_es_args(self.parser)
        self.args = self.parser.parse_args()
        self.es = Elasticsearch(
            f"https://{self.args.es_host}:{self.args.es_port}/",
            http_auth=(self.args.es_user, self.args.es_pass),
            timeout=30, max_retries=10, retry_on_timeout=True
        )

    def add_es_args(self, parser):
        """
        Adds elasticsearch arguments to a parser
        """
        parser.add_argument('--es-host', default='localhost',
                            help='Elasticsearch source host')
        parser.add_argument('--es-port', default=9200, type=int,
                            help='Elasticsearch source port')
        parser.add_argument('--es-user', default='',
                            help='Basic Auth user for ES (if applicable)')
        parser.add_argument('--es-pass', default='',
                            help='Basic Auth password for ES (if applicable)')
        return parser

    @staticmethod
    def get_simple_counts(es, index_name, doc_type, field_list):
        """ Extracts field counts from es index """
        total_docs = es.count(index=index_name,
                              doc_type=doc_type, body={})['count']

        counts = {'total': total_docs}
        for field in field_list:
            field_exists_query = {
                "query": {
                    "exists": {"field": field}
                }
            }
            field_count = es.search(index=index_name, doc_type=doc_type,
                                    body=field_exists_query)['hits']['total']
            counts[field] = field_count

        return counts

    @staticmethod
    def get_list_size_sums(es, index_name, doc_type, path_list):
        """ Aggregates sum of lengths of array fields in :path_list in index """
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
                        }
                    }
                }
            }

            size_sum = (es.search(index=index_name, doc_type=doc_type,
                                  body=list_size_sum_query)['aggregations']
                                                           ['outer_agg']
                                                           ['doc_count'])
            list_size_sums[path] = size_sum
        return list_size_sums

    @staticmethod
    def get_es_iterator(es, index_name, doc_type, query={}):
        """ Returns full index document iterator """
        doc_iterator = scan(es,
                            index=index_name,
                            doc_type=doc_type,
                            scroll='2m',
                            size=100,
                            query={'query': {'match_all': query}})
        return doc_iterator


if __name__ == '__main__':
    tester = DataTester()
    tester.run()

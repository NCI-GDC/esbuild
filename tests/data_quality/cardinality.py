import argparse
from pprint import pprint
from elasticsearch import Elasticsearch


def add_es_args(parser):
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
    parser.add_argument('--index-name', default='gdc_from_graph',
                        help='Choose esbuild index to test.')

    return parser


def get_simple_counts(es, index_name, doc_type, field_list):
    total_docs = es.count(index=index_name, doc_type=doc_type,
                          body={})['count']
    print '\ntotal [{}]: {}\n'.format(doc_type, total_docs)

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
        print field, field_count

    docs = es.search(index=index_name, doc_type=doc_type,
                     body={})['hits']['hits']

    return counts


def get_list_size_sums(es, index_name, doctype, path_list):
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

        size_sum = (es.search(index=index_name, doc_type=doctype,
                              body=list_size_sum_query)['aggregations']
                                                       ['outer_agg']
                                                       ['doc_count'])
        list_size_sums[path] = size_sum

        print path, size_sum
    return list_size_sums
    

def data_quality_test(args):
    index_name = args.index_name
    print('\nExtracting counts from {}\n'.format(index_name))

    auth = (args.es_user, args.es_pass)
    es = Elasticsearch(host=args.es_host, port=args.es_port,
                       http_auth=auth)
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
        ('case', ['samples', 'samples.portions', 'samples.portions.analytes',
                  'samples.portions.analytes.aliquots']),
        ('file', ['cases', 'associated_entities']),
    ]

    document_stats = {_: {} for _ in ['case', 'file', 'project', 'annotation']}

    # Simple count test cases
    for test_case in simple_test_cases:
        doc_type, field_list = test_case
        simple_counts = get_simple_counts(es, index_name, doc_type, field_list)
        document_stats[doc_type]['counts'] = simple_counts

    # Sum of lengths of array field test cases
    for test_case in array_test_cases:
        doc_type, path_list = test_case
        list_size_sums = get_list_size_sums(es, index_name, doc_type, path_list)
        document_stats[doc_type]['list_size_sums'] = list_size_sums

    print('\nES: {}, index: {}\n'.format(args.es_host, index_name))
    pprint(document_stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parses ES credentials')
    parser = add_es_args(parser)
    args = parser.parse_args()
    data_quality_test(args)


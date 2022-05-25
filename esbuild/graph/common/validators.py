def is_node_hidden(node):
    """Check whether node should be traversed but should not in any documents.

    Return True if the node should be traversed (and therefore must
    remain in the cache) but should not appear in any documents

    """
    # Hide all submitted_* node types from indices
    return node.label.startswith("submitted_") or node.label in [
        "archive",
        "raw_methylation_array",
    ]

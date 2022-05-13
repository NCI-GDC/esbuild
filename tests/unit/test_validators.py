import pytest
from gdcdatamodel import models

from esbuild.graph.common import validators


@pytest.mark.parametrize(
    "node, hidden",
    [
        (models.Case(), False),
        (models.Aliquot(), False),
        (models.Archive(), True),
        (models.MethylationBetaValue(), False),
        (models.SubmittedAlignedReads(), True),
        (models.SubmittedGenomicProfile(), True),
        (models.SubmittedGenotypingArray(), True),
        (models.SubmittedMethylationBetaValue(), True),
        (models.SubmittedTangentCopyNumber(), True),
        (models.SubmittedUnalignedReads(), True),
        (models.RawMethylationArray(), True),
    ],
)
def test_is_hidden_nodes(node, hidden):
    assert validators.is_node_hidden(node) is hidden

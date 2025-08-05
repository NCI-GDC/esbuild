from gdcdatamodel2 import models
from sqlalchemy import BigInteger, Boolean, desc, func

SORT_ORDER = (
    models.File._sysan["alignment_seen_docker_error"].cast(Boolean).nullsfirst(),
    func.random(),
)


def exome(graph, source):
    wxs = models.ExperimentalStrategy.name.astext == "WXS"
    illumina = models.Platform.name.astext.contains("Illumina")
    bam = models.DataFormat.name.astext == "BAM"
    all_file_ids_sq = (
        graph.nodes(models.File.node_id)
        .sysan(source=source)
        .distinct(models.File._sysan["cghub_legacy_sample_id"].astext)
        .filter(models.File.experimental_strategies.any(wxs))
        .filter(models.File.platforms.any(illumina))
        .filter(models.File.data_formats.any(bam))
        .order_by(
            models.File._sysan["cghub_legacy_sample_id"].astext,
            desc(models.File._sysan["cghub_upload_date"].cast(BigInteger)),
        )
        .subquery()
    )
    return graph.nodes(models.File).filter(
        models.File.node_id == all_file_ids_sq.c.node_id
    )


def wgs(graph, source):
    wgs = models.ExperimentalStrategy.name.astext == "WGS"
    illumina_plus_hiseq_x_ten = models.Platform.name.astext.contains("Illumina") | (
        models.Platform.name.astext == "HiSeq X Ten"
    )
    bam = models.DataFormat.name.astext == "BAM"
    all_file_ids_sq = (
        graph.nodes(models.File.node_id)
        .sysan(source=source)
        .distinct(models.File._sysan["cghub_legacy_sample_id"].astext)
        .filter(models.File.experimental_strategies.any(wgs))
        .filter(models.File.platforms.any(illumina_plus_hiseq_x_ten))
        .filter(models.File.data_formats.any(bam))
        .order_by(
            models.File._sysan["cghub_legacy_sample_id"].astext,
            desc(models.File._sysan["cghub_upload_date"].cast(BigInteger)),
        )
        .subquery()
    )
    return graph.nodes(models.File).filter(
        models.File.node_id == all_file_ids_sq.c.node_id
    )


def mirnaseq(graph, source):
    strategy = models.ExperimentalStrategy.name.astext == "miRNA-Seq"
    platform = models.Platform.name.astext.contains("Illumina")
    dataformat = models.DataFormat.name.astext == "BAM"

    subquery = (
        graph.nodes(models.File.node_id)
        .sysan(source=source)
        .distinct(models.File._sysan["cghub_legacy_sample_id"].astext)
        .filter(models.File.experimental_strategies.any(strategy))
        .filter(models.File.platforms.any(platform))
        .filter(models.File.data_formats.any(dataformat))
        .order_by(
            models.File._sysan["cghub_legacy_sample_id"].astext,
            desc(models.File._sysan["cghub_upload_date"].cast(BigInteger)),
        )
        .subquery()
    )
    return graph.nodes(models.File).filter(models.File.node_id == subquery.c.node_id)


def rnaseq(graph, source):
    strategy = models.ExperimentalStrategy.name.astext == "RNA-Seq"
    platform = models.Platform.name.astext.contains("Illumina")
    dataformat = models.DataFormat.name.astext.in_(["TAR", "TARGZ"])

    subquery = (
        graph.nodes(models.File.node_id)
        .sysan(source=source)
        .distinct(models.File._sysan["cghub_legacy_sample_id"].astext)
        .filter(models.File.experimental_strategies.any(strategy))
        .filter(models.File.platforms.any(platform))
        .filter(models.File.data_formats.any(dataformat))
        .order_by(
            models.File._sysan["cghub_legacy_sample_id"].astext,
            desc(models.File._sysan["cghub_upload_date"].cast(BigInteger)),
        )
        .subquery()
    )

    return graph.nodes(models.File).filter(models.File.node_id == subquery.c.node_id)

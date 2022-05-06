import itertools
import json
import os
import time
import uuid
from concurrent import futures
from typing import Any, Dict, Iterable, NamedTuple, Optional, Sequence, Tuple, Union

import datadog
import elasticsearch
import progressbar

from esbuild import gdc_elasticsearch, utils
from esbuild.graph.active import builder


def _extract_properties(mapping: dict, prefix: str = "") -> Iterable[str]:
    properties: Iterable[Tuple[str, Any]] = mapping["properties"].items()

    for name, mapping in properties:
        if "properties" in mapping:
            yield from _extract_properties(mapping, f"{prefix}{name}.")

        else:
            yield f"{prefix}{name}"


def _get_index_type(index_name: str) -> str:
    return index_name.split("_")[-1]


def _get_index_settings() -> Dict[str, Any]:
    index_settings = builder.ActiveESMapper.index_settings()
    settings = index_settings.setdefault("settings", {})
    settings["index.number_of_replicas"] = 0
    settings["index.number_of_shards"] = 1

    return index_settings


def _get_mappings() -> Dict[str, Any]:
    return {
        "annotation": builder.ActiveESMapper.get_annotation_es_mapping(),
        "case": builder.ActiveESMapper.get_case_es_mapping(),
        "file": builder.ActiveESMapper.get_file_es_mapping(),
        "project": builder.ActiveESMapper.get_project_es_mapping(),
    }


def _get_index_mappings(index_name: str, mappings: dict) -> dict:
    index_type = _get_index_type(index_name)

    if index_type not in mappings:
        raise ValueError(f"The index name: {index_name} is not valid.")

    return mappings[index_type]


def _read_text_file(path: Optional[str]) -> Optional[str]:
    if not (path and os.path.exists(path)):
        return None

    with open(path, "r") as f:
        return f.read()


def _read_json_file(path: Optional[str]) -> Optional[dict]:
    if not (path and os.path.exists(path)):
        return None

    with open(path, "r") as f:
        return json.load(f)


class ReindexingException(Exception):
    ...


class Arguments(NamedTuple):
    old_index: str
    new_index: str
    project_ids: Sequence[str]
    conflicts: str
    query: Optional[dict]
    source: Optional[Union[Sequence[str], Dict[str, Any], bool]]
    script_text: Optional[str]
    script_language: Optional[str]
    run_id: uuid.UUID


class EventLogger:
    def __init__(self, datadog: datadog.DogStatsd):
        self._datadog = datadog

    def _log_event(
        self,
        title: str,
        text: str,
        run_id: uuid.UUID,
        new_index: Optional[str] = None,
        task_id: Optional[str] = None,
        alert_type: str = "info",
    ):
        tags = ["process:reindex"]
        kwargs = {
            "title": title,
            "text": text,
            "alert_type": alert_type,
            "source_type_name": "esbuild",
            "tags": tags,
            "aggregation_key": run_id,
        }

        if new_index:
            tags.append(f"index:{new_index}")

        if task_id:
            tags.append(f"task:{task_id}")

        self._datadog.event(**kwargs)

    def log_info(
        self,
        title: str,
        text: str,
        run_id: uuid.UUID,
        new_index: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        self._log_event(title, text, run_id, new_index, task_id, alert_type="info")

    def log_error(
        self,
        title: str,
        text: str,
        run_id: uuid.UUID,
        new_index: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        self._log_event(title, text, run_id, new_index, task_id, alert_type="error")

    def log_success(
        self, title: str, text: str, run_id: uuid.UUID,
    ):
        self._log_event(title, text, run_id, alert_type="success")


class TaskProgressManager:
    def __init__(
        self, task_factory: gdc_elasticsearch.TaskFactory, event_logger: EventLogger
    ):
        self._task_factory = task_factory
        self._event_logger = event_logger

    def _wait_for_tasks_to_initialize(
        self, tasks: Iterable[gdc_elasticsearch.Task]
    ) -> Iterable[gdc_elasticsearch.Task]:
        task_ids = tuple(task.task_id for task in tasks)

        while any(not task.is_initailized() for task in tasks):
            time.sleep(5)

            tasks = self._task_factory.get_tasks(task_ids)

        return tasks

    def _track_progress(
        self, tasks: Iterable[gdc_elasticsearch.Task]
    ) -> Iterable[gdc_elasticsearch.Task]:
        task_ids = tuple(task.task_id for task in tasks)
        widgets = [
            "Reindexing: ",
            progressbar.Percentage(),
            " ",
            progressbar.Bar(marker="#", left="[", right="]"),
            " ",
            progressbar.ETA(),
            " ",
        ]
        max_value = sum(task.total for task in tasks)

        if not max_value:
            return tasks

        with progressbar.ProgressBar(max_value=max_value, widgets=widgets) as bar:
            while any(not task.completed for task in tasks):
                total = sum(task.current for task in tasks)

                bar.update(total)
                time.sleep(5)

                tasks = self._task_factory.get_tasks(task_ids)

        return tasks

    def _handle_failed_tasks(
        self, arguments: Dict[str, Arguments], tasks: Iterable[gdc_elasticsearch.Task]
    ) -> Iterable[str]:
        failed_tasks = filter(lambda t: t.failures, tasks)
        failed_indices = []

        for task in failed_tasks:
            reasons = tuple({failure["cause"]["reason"] for failure in task.failures})
            args = arguments[task.task_id]

            self._event_logger.log_error(
                "Reindexing Failed",
                f"Reasons: {reasons}.",
                args.run_id,
                args.new_index,
                task.task_id,
            )

            failed_indices.append(args.new_index)

        return failed_indices

    def _handle_errored_tasks(
        self, arguments: Dict[str, Arguments], tasks: Iterable[gdc_elasticsearch.Task]
    ) -> Iterable[str]:
        errored_tasks = filter(lambda t: t.error, tasks)
        errored_indices = []

        for task in errored_tasks:
            reason = task.error.get("caused_by", {}).get("reason")
            args = arguments[task.task_id]

            self._event_logger.log_error(
                "Reindexing Errored",
                f"Reasons: {reason}.",
                args.run_id,
                args.new_index,
                task.task_id,
            )

            errored_indices.append(args.new_index)

        return errored_indices

    def monitor(self, arguments: Dict[str, Arguments]):
        task_ids = arguments.keys()
        tasks = self._task_factory.get_tasks(task_ids)
        tasks = self._wait_for_tasks_to_initialize(tasks)
        tasks = self._track_progress(tasks)

        if any(task.has_failed() for task in tasks):
            failed_indices = self._handle_failed_tasks(arguments, tasks)
            errored_indices = self._handle_errored_tasks(arguments, tasks)
            message = ", ".join(itertools.chain(failed_indices, errored_indices))

            raise ReindexingException(
                f"Encounted failures/errors while reindexing: {message}"
            )


class IndexPair(NamedTuple):
    old_index: str
    new_index: str


class Reindexer:
    def __init__(
        self,
        es: elasticsearch.Elasticsearch,
        release_helper: utils.ReleaseHelper,
        progress_manager: TaskProgressManager,
        event_logger: EventLogger,
        executor: futures.Executor,
    ):
        self._es = es
        self._release_helper = release_helper
        self._executor = executor
        self._progress_manager = progress_manager
        self._event_logger = event_logger

    def _get_source(self, old_index_name: str, current_mapping: dict) -> Dict[str, Any]:
        old_mapping = self._es.indices.get_mapping(index=old_index_name)[
            old_index_name
        ]["mappings"]
        old_properties = frozenset(_extract_properties(old_mapping))
        new_properties = frozenset(_extract_properties(current_mapping))

        return {"excludes": tuple(old_properties - new_properties)}

    def _get_indices(
        self, old_index: str, new_index: str, index_types: Sequence[str],
    ) -> Iterable[IndexPair]:
        if not index_types:
            return (IndexPair(old_index, new_index),)

        old_indices = (f"{old_index}_{index_type}" for index_type in index_types)
        new_indices = (f"{new_index}_{index_type}" for index_type in index_types)

        return (
            IndexPair(old_index, new_index)
            for old_index, new_index in zip(old_indices, new_indices)
        )

    def _create_new_index(self, args: Arguments, mappings: dict, settings: dict):
        if not self._es.indices.exists(index=args.new_index):
            body = dict(mappings=mappings, **settings)

            self._event_logger.log_info(
                "Index Created",
                f"Created index: {args.new_index}",
                args.run_id,
                args.new_index,
            )

            self._es.indices.create(index=args.new_index, body=body)
            self._es.indices.refresh(index=args.new_index)
        else:
            self._event_logger.log_info(
                "Index Found",
                f"Index: {args.new_index} already exists.",
                args.run_id,
                args.new_index,
            )

    def _start_reindexing_task(self, args: Arguments,) -> str:
        source = {"index": args.old_index, "_source": args.source}
        dest = {"index": args.new_index}

        if args.query:
            source["query"] = args.query

        reindex_body = {
            "conflicts": args.conflicts,
            "source": source,
            "dest": dest,
        }

        if args.script_text and args.script_language:
            reindex_body["script"] = {
                "source": args.script_text,
                "lang": args.script_language,
            }

        task_info = self._es.reindex(
            body=reindex_body, refresh=True, wait_for_completion=False
        )

        task_id: str = task_info["task"]

        self._event_logger.log_info(
            "Reindexing Started",
            f"Reindexing started in Elasticsearch. Task: {task_id}",
            args.run_id,
            args.new_index,
            task_id,
        )
        print(f"Started reindexing for {args.new_index}. Task: {task_id}")

        return task_id

    def _build_project_query(
        self, new_index_name: str, project_ids: Sequence[str]
    ) -> dict:
        index_type = _get_index_type(new_index_name)

        self._release_helper.delete_docs_from_index(
            index_name=new_index_name,
            index_type=index_type,
            projects_to_delete=project_ids,
        )

        return self._release_helper.get_project_docs_query(index_type, project_ids)

    def _reindex(self, args: Arguments, settings: dict, mappings: dict,) -> str:
        mappings = _get_index_mappings(args.new_index, mappings)
        source = args.source or self._get_source(args.old_index, mappings)
        query = (
            self._build_project_query(args.new_index, args.project_ids)
            if args.project_ids
            else args.query
        )
        args = Arguments(
            args.old_index,
            args.new_index,
            args.project_ids,
            args.conflicts,
            query,
            source,
            args.script_text,
            args.script_language,
            args.run_id,
        )

        self._create_new_index(args, mappings, settings)
        task_id = self._start_reindexing_task(args)

        return task_id

    def reindex(
        self,
        old_index: str,
        new_index: str,
        index_types: Sequence[str] = (),
        project_ids: Sequence[str] = (),
        conflicts: str = "abort",
        source: Optional[Union[Sequence[str], bool]] = None,
        query: Optional[str] = None,
        script: Optional[str] = None,
        script_language: Optional[str] = None,
    ):
        """Starts the Elasticsearch reindex process which moves the data from
        an existing index into a different (new or existing) index. If the new
        index has not yet been created this process will create the new index
        using the current GDC models before calling the reindexing process.

        Args:
            old_index: The name/prefix of the source index/indices which is to be reindexed.
            new_index: The name/prefix of the destination index/indices.
            index_types: The postfixes to be used if a prefix is given for old/new_index
            project_ids: A list of project ids to restict the data reindexed from the source.
            conflicts: Determins if the reindex will abort or proceed if it encounters any
                conflicts.
            source: A list of fields to included from the source index
            query: A file path containing a query to determine what data will be reindexed
                from the source index
            script: A file path containing a sciprt what will be run during the reindexing
                processes
            script_language: The language that the script, if any, is in.
        """
        try:
            run_id = uuid.uuid4()
            indices = self._get_indices(old_index, new_index, index_types)
            index_settings = _get_index_settings()
            mappings = _get_mappings()
            query_data = _read_json_file(query)
            script_text = _read_text_file(script)
            arguments = tuple(
                Arguments(
                    pair.old_index,
                    pair.new_index,
                    project_ids,
                    conflicts,
                    query_data,
                    source,
                    script_text,
                    script_language,
                    run_id,
                )
                for pair in indices
            )

            print(f"Beginning run: {run_id}")
            self._event_logger.log_info(
                "Reindexing Command Called", f"Reindexing run: {run_id}", run_id,
            )

            threads = tuple(
                (
                    args,
                    self._executor.submit(
                        self._reindex, args, index_settings, mappings,
                    ),
                )
                for args in arguments
            )
            arguments_by_task = {thread.result(): args for args, thread in threads}

            self._progress_manager.monitor(arguments_by_task)
            self._event_logger.log_success(
                "Reindexing Command Succeeded", f"Reindexing run: {run_id}", run_id,
            )

        except Exception as e:
            # TODO: Log exception
            print(f"Reindexing Failed: {e}")

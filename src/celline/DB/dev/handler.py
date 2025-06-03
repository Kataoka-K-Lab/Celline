from abc import ABC, abstractmethod
from dataclasses import dataclass
import gc
import inspect
import os
from typing import Dict, Final, Generic, List, Optional, Type, TypeVar, Union

import polars as pl
import toml

from celline.DB.dev.model import BaseModel, BaseSchema
from celline.config import Config
from celline.plugins.reflection.activator import Activator
from celline.plugins.reflection.method import MethodInfo
from celline.plugins.reflection.module import Module
from celline.plugins.reflection.type import TypeC
from celline.utils.exceptions import NullPointException
from celline.log.logger import get_logger

TProject = TypeVar("TProject", bound=BaseModel)
TSample = TypeVar("TSample", bound=BaseModel)
TRun = TypeVar("TRun", bound=BaseModel)


class BaseHandler(Generic[TProject, TSample, TRun], ABC):
    """## Handle genome database"""

    _project: Optional[TProject] = None
    _sample: Optional[TSample] = None
    _run: Optional[TRun] = None
    _df: pl.DataFrame
    _samples: Dict[str, str] = {}
    """Samples which is composed by SampleID(key) and Title(value)"""

    def __init__(self) -> None:
        """#### Set acceptable ID"""
        BaseHandler.SAMPLE_PATH: Final[str] = f"{Config.PROJ_ROOT}/samples.toml"
        if os.path.isfile(BaseHandler.SAMPLE_PATH):
            with open(BaseHandler.SAMPLE_PATH, mode="r", encoding="utf-8") as f:
                self._samples = toml.load(f)
        else:
            with open(BaseHandler.SAMPLE_PATH, mode="w", encoding="utf-8") as f:
                toml.dump(self._samples, f)

    @abstractmethod
    def resolver(self, acceptable_id: str) -> Union[TProject, TSample, TRun]:
        return

    @property
    def project(self) -> TProject:
        """Set project system"""
        if self._project is None:
            raise ModuleNotFoundError("_project variable are not set")
        return self._project

    @property
    def sample(self) -> TSample:
        """Set sample system"""
        if self._sample is None:
            raise ModuleNotFoundError("_sample variable are not set")
        return self._sample

    @property
    def run(self) -> TRun:
        """Set project system"""
        if self._run is None:
            raise ModuleNotFoundError("_run variable are not set")
        return self._run

    def add(self, acceptable_id: str, force_search=False):
        """Add to DB & samples.toml with acceptable_id"""
        logger = get_logger(__name__)
        logger.info(f"Starting to add {acceptable_id} to database")
        
        resolver = self.resolver(acceptable_id)
        if isinstance(self.project, resolver):
            logger.info(f"Identified {acceptable_id} as project type, fetching project data")
            project: BaseSchema = self.project.search(acceptable_id, force_search)
            sample_ids = project.children
            if sample_ids is None:
                raise NullPointException(
                    f"children were not found in target project: {project.key}."
                )
            sample_ids = sample_ids.split(",")
            logger.info(f"Found {len(sample_ids)} samples in project {acceptable_id}: {sample_ids}")
            
            samples: List[BaseSchema] = []
            for i, sample_id in enumerate(sample_ids, 1):
                logger.info(f"Fetching sample {i}/{len(sample_ids)}: {sample_id}")
                try:
                    sample = self.sample.search(sample_id)
                    samples.append(sample)
                    logger.info(f"Successfully fetched sample {sample_id}")
                except Exception as e:
                    logger.error(f"Failed to fetch sample {sample_id}: {str(e)}")
                    raise
            for j, sample in enumerate(samples, 1):
                logger.info(f"Processing sample {j}/{len(samples)}: {sample.key}")
                if sample.title is None:
                    sample.title = ""
                run_ids = sample.children
                if run_ids is not None:
                    run_ids = run_ids.split(",")
                    logger.info(f"Found {len(run_ids)} runs for sample {sample.key}")
                    for k, target_run_id in enumerate(run_ids, 1):
                        logger.info(f"Fetching run {k}/{len(run_ids)}: {target_run_id}")
                        try:
                            self.run.search(target_run_id)
                            logger.info(f"Successfully fetched run {target_run_id}")
                        except Exception as e:
                            logger.error(f"Failed to fetch run {target_run_id}: {str(e)}")
                            raise
                self._add_to_projsample({str(sample.key): sample.title})
                logger.info(f"Added sample {sample.key} to project samples")
        elif isinstance(self.sample, resolver):
            logger.info(f"Identified {acceptable_id} as sample type, fetching sample data")
            sample: BaseSchema = self.sample.search(acceptable_id, force_search)
            if sample.title is None:
                sample.title = ""
            runs = sample.children
            if runs is not None:
                run_list = runs.split(",")
                logger.info(f"Found {len(run_list)} runs for sample {acceptable_id}")
                for i, run_id in enumerate(run_list, 1):
                    logger.info(f"Fetching run {i}/{len(run_list)}: {run_id}")
                    try:
                        self.run.search(run_id)
                        logger.info(f"Successfully fetched run {run_id}")
                    except Exception as e:
                        logger.error(f"Failed to fetch run {run_id}: {str(e)}")
                        raise
            if sample.parent is not None:
                logger.info(f"Fetching parent project {sample.parent} for sample {acceptable_id}")
                self.project.search(sample.parent, force_search)
            self._add_to_projsample({str(sample.key): sample.title})
            logger.info(f"Added sample {acceptable_id} to project samples")
        elif isinstance(self.run, resolver):
            run: BaseSchema = self.run.search(acceptable_id, force_search)
            if run.parent is None:
                raise KeyError("Parent run is None")
            sample = self.sample.search(run.parent, force_search=force_search)
            if sample.children is not None:
                if run.key not in sample.children.split(","):
                    if sample.children == "":
                        __d = []
                    else:
                        __d = sample.children.split(",")
                    __d.append(f"{run.key}")
                    sample.children = ",".join(__d)
            else:
                sample.children = f"{run.key}"
            self.project.search(str(sample.key), force_search)
            if sample.title is None:
                sample.title = ""
            self._add_to_projsample({str(sample.key): sample.title})

    def sync(self, force_research=False):
        """Sync DB from samples.toml"""
        for sample in self._samples:
            self.add(sample, force_search=force_research)

    def _add_to_projsample(
        self, sample_info: Union[Dict[str, str], List[Dict[str, str]]]
    ):
        if isinstance(sample_info, list):
            for sample in sample_info:
                self._add_to_projsample(sample)
            return
        self._flush_to_append(
            list(str(k) for k in sample_info.keys())[0], list(sample_info.values())[0]
        )

    def _flush_to_append(self, sample_id: str, title: str):
        if sample_id in self._samples:
            return
        self._samples[sample_id] = title
        TEXT_TO_APPEND: Final[str] = f'\n{sample_id} = "{title}"'
        with open(BaseHandler.SAMPLE_PATH, mode="a", encoding="utf-8") as f:
            f.write(TEXT_TO_APPEND)


THandler = TypeVar("THandler", bound=BaseHandler)


class HandleResolver:
    _constructed = False

    @classmethod
    def _define_resolver_constructor(cls):
        def _add(t: TypeC):
            cls._handlers[t.GetMethod("resolver")] = Activator.CreateInstance(t)

        if not cls._constructed:
            module = Module.GetModules(f"{Config.EXEC_ROOT}/celline/DB/handler")
            cls._handlers: Dict[MethodInfo, BaseHandler] = {}
            cls._constructed = True
            module.ForEach(lambda mod: mod.GetTypes().ForEach(lambda t: _add(t)))

    @classmethod
    def resolve(cls, acceptable_id: str):
        cls._define_resolver_constructor()
        use_handler: Optional[BaseHandler] = None
        for met, obj in cls._handlers.items():
            result = met.Invoke(obj, acceptable_id=acceptable_id)
            if result is not None:
                use_handler = obj
                break
        return use_handler

        # inherited_classes = [
        #     obj
        #     for obj in gc.get_objects()
        #     if inspect.isclass(obj) and issubclass(obj, BaseHandler)
        # ]
        # for inh in inherited_classes:
        #     # instance = inh()  # インスタンス作成
        #     # print(instance.get_sample())
        #     print(inh)
        # instance = subclass()  # インスタンス作成
        # print(instance.get_sample())

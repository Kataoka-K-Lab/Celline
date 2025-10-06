from abc import ABC, abstractmethod
from dataclasses import dataclass
import gc
import inspect
import os
from typing import Dict, Final, Generic, List, Optional, Type, TypeVar, Union

from celline.DB.dev.model import BaseModel, BaseSchema
from celline.DB.dev.excel_handler import ExcelMetadataHandler
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
    _excel_handler: ExcelMetadataHandler
    """Excel metadata handler"""

    def __init__(self, use_ai: bool = False, ai_provider: str = "auto") -> None:
        """#### Initialize Excel handler

        Args:
            use_ai: Enable AI metadata extraction
            ai_provider: AI provider to use ("openai", "claude", or "auto")
        """
        if Config.current in Config.runnings:
            excel_path = f"{Config.runnings[Config.current].PROJ_ROOT}/metadata.xlsx"
        else:
            raise RuntimeError("Config not initialized. Please create a Config instance first.")
        self._excel_handler = ExcelMetadataHandler(excel_path)
        self._use_ai = use_ai
        self._ai_provider = ai_provider

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
        """Add to DB & metadata.xlsx with acceptable_id"""
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
                sample = self.sample.search(sample_id)
                samples.append(sample)
                logger.info(f"Successfully fetched sample {sample_id}")
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
                        self.run.search(target_run_id)
                        logger.info(f"Successfully fetched run {target_run_id}")
                logger.info(f"Sample {sample.key} already added to Excel by model.add_schema()")

                # Extract AI metadata if enabled
                if self._use_ai:
                    self._extract_ai_metadata(str(sample.key), sample)

            # Add all samples to available_samples
            logger.info(f"Adding {len(sample_ids)} samples to available_samples")
            self._excel_handler.add_multiple_to_available_samples(sample_ids)

            logger.info("All data added, validating integrity...")
            self._validate_all_integrity()

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
                    self.run.search(run_id)
                    logger.info(f"Successfully fetched run {run_id}")
            if sample.parent is not None:
                logger.info(f"Fetching parent project {sample.parent} for sample {acceptable_id}")
                self.project.search(sample.parent, force_search)
            logger.info(f"Sample {acceptable_id} already added to Excel by model.add_schema()")

            # Extract AI metadata if enabled
            if self._use_ai:
                self._extract_ai_metadata(acceptable_id, sample)

            # Add to available_samples
            logger.info(f"Adding {acceptable_id} to available_samples")
            self._excel_handler.add_to_available_samples(acceptable_id)

            logger.info("All data added, validating integrity...")
            self._validate_all_integrity()

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
            logger.info(f"Run {acceptable_id} and related data already added to Excel by model.add_schema()")

            logger.info("All data added, validating integrity...")
            self._validate_all_integrity()

    def _extract_ai_metadata(self, accession_id: str, schema: BaseSchema) -> Dict:
        """
        Extract AI metadata for a sample and add to Excel.

        Args:
            accession_id: Sample accession ID
            schema: Schema instance with raw_link or other metadata

        Returns:
            Dictionary with AI-extracted metadata
        """
        if not self._use_ai:
            return {}

        logger = get_logger(__name__)

        try:
            from celline.utils.ai_metadata import AIMetadataExtractor
            import requests
            from bs4 import BeautifulSoup
            from rich.console import Console

            console = Console()

            # Try to get URL from schema
            url = None
            if hasattr(schema, 'raw_link') and schema.raw_link:
                # Use raw_link if available
                url = str(schema.raw_link)
            else:
                # Try to construct URL based on accession pattern
                if accession_id.startswith('GSM'):
                    url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession_id}"
                elif accession_id.startswith('E-'):
                    url = f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{accession_id}"
                elif accession_id.startswith('SAMEA') or accession_id.startswith('SAMN'):
                    url = f"https://www.ebi.ac.uk/biosamples/samples/{accession_id}"

            if not url:
                logger.info(f"No URL available for AI extraction for {accession_id}")
                return {}

            logger.info(f"Fetching URL for AI extraction: {url}")
            console.print(f"[cyan]Fetching metadata from {url}...[/cyan]")

            # Fetch page content
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Extract text from HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator='\n', strip=True)

            # Extract metadata using AI
            extractor = AIMetadataExtractor(provider=self._ai_provider)
            ai_metadata = extractor.extract_metadata(text, accession_id)

            if ai_metadata:
                # Add AI metadata to sample sheet
                # Prefix AI fields with "ai_" to distinguish them
                current_record = self._excel_handler.get_record("samples", accession_id)
                if current_record:
                    # Merge AI metadata with existing record
                    for key, value in ai_metadata.items():
                        if value and value != "unknown":
                            current_record[f"ai_{key}"] = value

                    self._excel_handler.add_or_update_record("samples", current_record)
                    logger.info(f"AI metadata added to {accession_id}: {len(ai_metadata)} fields")
                    console.print(f"[green]✓ AI metadata added: {', '.join(ai_metadata.keys())}[/green]")

            return ai_metadata

        except ImportError as e:
            logger.warning(f"AI extraction dependencies not installed: {e}")
            from rich.console import Console
            Console().print(f"[yellow]⚠ AI extraction requires: beautifulsoup4, requests, python-dotenv[/yellow]")
            return {}
        except Exception as e:
            logger.warning(f"AI metadata extraction failed for {accession_id}: {e}")
            return {}

    def _validate_all_integrity(self):
        """Validate data integrity across all sheets after all data has been added."""
        logger = get_logger(__name__)
        try:
            integrity_result = self._excel_handler.validate_data_integrity()
            if not integrity_result.is_valid:
                error_msgs = [
                    f"Sheet '{e.sheet}' Row {e.row} Column '{e.column}': {e.error_type} - {e.message}"
                    for e in integrity_result.errors
                ]
                logger.error(f"Data integrity validation failed:\n" + "\n".join(error_msgs))
                raise ValueError(f"Data integrity validation failed:\n" + "\n".join(error_msgs))

            # Log warnings if any
            if integrity_result.warnings:
                import warnings
                for w in integrity_result.warnings:
                    warning_msg = f"Sheet '{w.sheet}' Row {w.row} Column '{w.column}': {w.error_type} - {w.message}"
                    logger.warning(warning_msg)
                    warnings.warn(warning_msg, UserWarning)

            logger.info("Data integrity validation passed")
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            raise

    def sync(self, force_research=False):
        """Sync DB from metadata.xlsx"""
        sample_keys = self._excel_handler.get_all_keys("samples")
        for sample_id in sample_keys:
            self.add(sample_id, force_search=force_research)


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

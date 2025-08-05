from typing import Union, Optional, Dict, List
import os
import urllib.request
import urllib.parse
from pathlib import Path as PathLib
import requests
from celline.DB.dev.handler import BaseHandler
from celline.DB.model import AE_Study, AE_Sample, AE_Run  
from celline.log.logger import get_logger
from celline.utils.path import Path as CellinePath


class ArrayExpressHandler(BaseHandler[AE_Study, AE_Sample, AE_Run]):
    """Handler for ArrayExpress (BioStudies) accessions
    
    Supports:
    - E-MTAB: MTAB studies (most common)
    - E-GEOD: GEO studies in ArrayExpress
    - E-MEXP: MEXP studies  
    - E-TABM: TABM studies
    - E-MAGE: MAGE studies
    - E-AFMX: Affymetrix studies
    
    Integration with:
    - BioStudies API (migrated from ArrayExpress API)
    - BioSamples API for sample metadata
    - ENA API for sequencing runs
    - FTP for file downloads
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(__name__)
        self.base_ftp_url = "https://ftp.ebi.ac.uk/biostudies/arrayexpress"
        self.ena_ftp_base = "ftp.sra.ebi.ac.uk/vol1"
    
    def resolver(self, acceptable_id: str) -> Optional[Union[AE_Study, AE_Sample, AE_Run]]:
        """Resolve ArrayExpress/ENA accession ID to appropriate model class"""
        # Initialize model instances
        self._project = AE_Study()    # ArrayExpress Studies
        self._sample = AE_Sample()    # BioSamples / ArrayExpress Samples
        self._run = AE_Run()         # ENA Runs
        
        # Study level - ArrayExpress experiments
        if self._is_arrayexpress_study(acceptable_id):
            self.logger.info(f"Resolved {acceptable_id} as ArrayExpress Study")
            return AE_Study
        
        # Sample level - BioSamples or ArrayExpress samples
        elif self._is_biosample_id(acceptable_id) or self._is_sample_name(acceptable_id):
            self.logger.info(f"Resolved {acceptable_id} as ArrayExpress Sample")
            return AE_Sample
        
        # Run level - ENA runs
        elif self._is_ena_run(acceptable_id):
            self.logger.info(f"Resolved {acceptable_id} as ENA Run")
            return AE_Run
        
        # Unknown accession pattern
        else:
            self.logger.warning(f"Unknown ArrayExpress/ENA accession pattern: {acceptable_id}")
            return None
    
    def _is_arrayexpress_study(self, accession_id: str) -> bool:
        """Check if ID is an ArrayExpress study accession"""
        return accession_id.startswith(("E-MTAB-", "E-GEOD-", "E-MEXP-", "E-TABM-", "E-MAGE-", "E-AFMX-"))
    
    def _is_biosample_id(self, accession_id: str) -> bool:
        """Check if ID is a BioSamples accession"""
        return accession_id.startswith(("SAMEA", "SAMN", "SAMD"))
    
    def _is_sample_name(self, accession_id: str) -> bool:
        """Check if ID could be a sample name (fallback)"""
        # Accept various sample naming conventions but be more restrictive
        return (len(accession_id) > 0 and 
                not self._is_ena_run(accession_id) and
                not accession_id.startswith(("GSE", "GSM", "SRP", "INVALID")) and
                ("sample" in accession_id.lower() or "_" in accession_id or "-" in accession_id))
    
    def _is_ena_run(self, accession_id: str) -> bool:
        """Check if ID is an ENA run accession"""
        return accession_id.startswith(("ERR", "SRR", "DRR"))
    
    def download(self, acceptable_id: str, output_dir: str, **kwargs) -> bool:
        """Download ArrayExpress data files
        
        Args:
            acceptable_id: ArrayExpress/ENA accession ID
            output_dir: Directory to save downloaded files
            **kwargs: Additional download options
                - include_raw: Download raw data files (default: True)
                - include_processed: Download processed data files (default: True)
                - include_metadata: Download metadata files (default: True)
                - max_file_size: Maximum file size in bytes (default: None)
            
        Returns:
            bool: Success status
        """
        try:
            model_class = self.resolver(acceptable_id)
            if model_class is None:
                self.logger.error(f"Cannot resolve accession ID: {acceptable_id}")
                return False
            
            # Handle different types
            if model_class == AE_Run:
                return self._download_run_data(acceptable_id, output_dir, **kwargs)
            elif model_class == AE_Sample:
                return self._download_sample_data(acceptable_id, output_dir, **kwargs)
            elif model_class == AE_Study:
                return self._download_study_data(acceptable_id, output_dir, **kwargs)
            else:
                self.logger.error(f"Download not supported for {model_class}")
                return False
                
        except Exception as e:
            self.logger.error(f"Download failed for {acceptable_id}: {str(e)}")
            return False
    
    def _download_run_data(self, run_id: str, output_dir: str, **kwargs) -> bool:
        """Download ENA run data following Celline directory structure"""
        try:
            # Get run metadata
            run_data = self._run.search(run_id)
            if not run_data.raw_link:
                self.logger.warning(f"No download links available for run {run_id}")
                return False
            
            # Determine parent sample for directory structure
            parent_sample = run_data.parent or f"sample_{run_id}"
            
            # Create Celline-style directory structure
            # Use sample accession as project_id and sample_id
            celline_path = CellinePath(run_data.sample_accession or parent_sample, parent_sample)
            celline_path.prepare()
            
            # Create run-specific directory
            run_dir = PathLib(celline_path.resources_sample_raw_fastqs) / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            
            # Download files
            urls = run_data.raw_link.split(",")
            success_count = 0
            include_raw = kwargs.get("include_raw", True)
            max_file_size = kwargs.get("max_file_size", None)
            
            if not include_raw:
                self.logger.info(f"Skipping raw data download for {run_id} (include_raw=False)")
                return True
            
            for url in urls:
                if not url.strip():
                    continue
                    
                filename = url.split("/")[-1]
                output_path = run_dir / filename
                
                try:
                    # Check file size if limit specified
                    if max_file_size:
                        if not self._check_file_size(url, max_file_size):
                            self.logger.warning(f"Skipping {filename} - exceeds size limit")
                            continue
                    
                    self.logger.info(f"Downloading {filename} from {url}")
                    
                    # Use appropriate download method based on URL
                    if url.startswith("ftp://"):
                        urllib.request.urlretrieve(url, output_path)
                    else:
                        response = requests.get(url, stream=True, timeout=300)
                        response.raise_for_status()
                        
                        with open(output_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                    
                    success_count += 1
                    self.logger.info(f"Successfully downloaded {filename}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to download {filename}: {str(e)}")
            
            # Create download manifest
            manifest_path = run_dir / "download_manifest.txt"
            with open(manifest_path, 'w') as f:
                f.write(f"# ArrayExpress/ENA Download Manifest for {run_id}\\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\\n")
                f.write(f"# Parent Sample: {parent_sample}\\n")
                f.write(f"# Library Strategy: {run_data.library_strategy}\\n")
                f.write(f"# Platform: {run_data.platform}\\n")
                f.write(f"# Instrument: {run_data.instrument_model}\\n")
                f.write("\\n# Downloaded Files:\\n")
                for url in urls:
                    if url.strip():
                        filename = url.split("/")[-1]
                        f.write(f"{filename}\\t{url}\\n")
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Run download failed for {run_id}: {str(e)}")
            return False
    
    def _download_sample_data(self, sample_id: str, output_dir: str, **kwargs) -> bool:
        """Download sample-level data (downloads all associated runs)"""
        try:
            # Get sample metadata - need parent study for SDRF parsing
            parent_study = kwargs.get("parent_study")
            sample_data = self._sample.search(sample_id, parent_study=parent_study)
            
            if not sample_data.children:
                self.logger.warning(f"No runs found for sample {sample_id}")
                return False
            
            # Create sample-level directory and metadata
            project_id = sample_data.parent or sample_id
            celline_path = CellinePath(project_id, sample_id)
            celline_path.prepare()
            
            # Create sample metadata file
            sample_info_path = PathLib(celline_path.data_sample) / "arrayexpress_sample_info.txt"
            sample_info_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(sample_info_path, 'w') as f:
                f.write(f"# ArrayExpress Sample Information for {sample_id}\\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\\n")
                f.write(f"Sample ID: {sample_id}\\n")
                f.write(f"Title: {sample_data.title}\\n")
                f.write(f"Summary: {sample_data.summary}\\n")
                f.write(f"Species: {sample_data.species}\\n")
                f.write(f"Organism: {sample_data.organism}\\n")
                f.write(f"Tissue: {sample_data.tissue}\\n")
                f.write(f"Cell Type: {sample_data.cell_type}\\n")
                f.write(f"Disease: {sample_data.disease}\\n")
                f.write(f"Treatment: {sample_data.treatment}\\n")
                f.write(f"Parent Study: {sample_data.parent}\\n")
                f.write(f"Associated Runs: {sample_data.children}\\n")
                f.write(f"Assay IDs: {sample_data.assay_ids}\\n")
            
            # Download all runs for this sample
            run_ids = sample_data.children.split(",")
            success_count = 0
            
            for run_id in run_ids:
                if run_id.strip():
                    if self._download_run_data(run_id.strip(), output_dir, **kwargs):
                        success_count += 1
            
            self.logger.info(f"Sample {sample_id}: Downloaded {success_count}/{len(run_ids)} runs successfully")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Sample download failed for {sample_id}: {str(e)}")
            return False
    
    def _download_study_data(self, study_id: str, output_dir: str, **kwargs) -> bool:
        """Download study-level data (metadata + samples/runs)"""
        try:
            # Get study metadata
            study_data = self._project.search(study_id)
            
            # Create study-level directory and metadata
            from celline.config import Config
            study_info_dir = PathLib(Config.PROJ_ROOT) / "data" / study_id
            study_info_dir.mkdir(parents=True, exist_ok=True)
            
            # Download MAGE-TAB files (IDF, SDRF, ADF)
            include_metadata = kwargs.get("include_metadata", True)
            if include_metadata:
                self._download_magetab_files(study_id, study_info_dir)
            
            # Create study metadata file
            study_info_path = study_info_dir / "arrayexpress_study_info.txt"
            with open(study_info_path, 'w') as f:
                f.write(f"# ArrayExpress Study Information for {study_id}\\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\\n")
                f.write(f"Study ID: {study_id}\\n")
                f.write(f"Title: {study_data.title}\\n")
                f.write(f"Summary: {study_data.summary}\\n")
                f.write(f"Organism: {study_data.organism}\\n")
                f.write(f"Experiment Type: {study_data.experiment_type}\\n")
                f.write(f"Release Date: {study_data.release_date}\\n")
                f.write(f"Submission Date: {study_data.submission_date}\\n")
                f.write(f"PubMed ID: {study_data.pubmed_id}\\n")
                f.write(f"DOI: {study_data.doi}\\n")
                f.write(f"Associated Samples: {study_data.children}\\n")
            
            # Download samples and runs if requested
            include_raw = kwargs.get("include_raw", True)
            if include_raw and study_data.children:
                sample_ids = study_data.children.split(",")
                success_count = 0
                
                for sample_id in sample_ids:
                    if sample_id.strip():
                        # Pass parent study for SDRF parsing
                        kwargs_with_study = kwargs.copy()
                        kwargs_with_study["parent_study"] = study_id
                        
                        if self._download_sample_data(sample_id.strip(), output_dir, **kwargs_with_study):
                            success_count += 1
                
                self.logger.info(f"Study {study_id}: Downloaded {success_count}/{len(sample_ids)} samples successfully")
                return success_count > 0
            
            return True
            
        except Exception as e:
            self.logger.error(f"Study download failed for {study_id}: {str(e)}")
            return False
    
    def _download_magetab_files(self, study_id: str, output_dir: PathLib) -> bool:
        """Download MAGE-TAB files (IDF, SDRF, ADF)"""
        try:
            ftp_path = self._construct_ftp_path(study_id)
            base_url = f"{self.base_ftp_url}/{ftp_path}"
            
            # MAGE-TAB file types to download
            file_types = ["idf.txt", "sdrf.txt", "adf.txt"]
            success_count = 0
            
            for file_type in file_types:
                filename = f"{study_id}.{file_type}"
                file_url = f"{base_url}/{filename}"
                output_path = output_dir / filename
                
                try:
                    response = requests.get(file_url, timeout=60)
                    if response.status_code == 200:
                        with open(output_path, 'w', encoding='utf-8') as f:
                            f.write(response.text)
                        self.logger.info(f"Downloaded {filename}")
                        success_count += 1
                    elif response.status_code == 404:
                        self.logger.info(f"File {filename} not available (404)")
                    else:
                        self.logger.warning(f"Failed to download {filename}: HTTP {response.status_code}")
                        
                except Exception as e:
                    self.logger.error(f"Error downloading {filename}: {str(e)}")
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"MAGE-TAB download failed for {study_id}: {str(e)}")
            return False
    
    def _construct_ftp_path(self, study_id: str) -> str:
        """Construct FTP path for study files"""
        if study_id.startswith("E-MTAB-"):
            number = study_id.split("-")[-1]
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-MTAB/{group}/{study_id}"
        elif study_id.startswith("E-GEOD-"):
            number = study_id.split("-")[-1]
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-GEOD/{group}/{study_id}"
        else:
            prefix = study_id.split("-")[1] if "-" in study_id else "UNKNOWN"
            number = study_id.split("-")[-1] if "-" in study_id else "000"
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-{prefix}/{group}/{study_id}"
    
    def _check_file_size(self, url: str, max_size: int) -> bool:
        """Check if file size is within limits"""
        try:
            response = requests.head(url, timeout=30)
            if response.status_code == 200:
                content_length = response.headers.get('content-length')
                if content_length:
                    file_size = int(content_length)
                    return file_size <= max_size
        except Exception as e:
            self.logger.warning(f"Could not check file size for {url}: {e}")
        
        return True  # Allow download if size check fails
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in standard format"""
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def parse_magetab(self, study_id: str) -> Dict[str, any]:
        """Parse MAGE-TAB files to extract structured metadata
        
        Returns:
            dict: Parsed metadata including study info, samples, and file mappings
        """
        try:
            ftp_path = self._construct_ftp_path(study_id)
            base_url = f"{self.base_ftp_url}/{ftp_path}"
            
            result = {
                "study_id": study_id,
                "idf_data": {},
                "sdrf_data": [],
                "adf_data": {},
                "samples": {},
                "assays": {},
                "files": {}
            }
            
            # Parse IDF (Investigation Design Format)
            idf_url = f"{base_url}/{study_id}.idf.txt"
            result["idf_data"] = self._parse_idf(idf_url)
            
            # Parse SDRF (Sample and Data Relationship Format)
            sdrf_url = f"{base_url}/{study_id}.sdrf.txt"
            result["sdrf_data"], result["samples"], result["assays"] = self._parse_sdrf(sdrf_url)
            
            return result
            
        except Exception as e:
            self.logger.error(f"MAGE-TAB parsing failed for {study_id}: {str(e)}")
            return {"error": str(e)}
    
    def _parse_idf(self, idf_url: str) -> Dict[str, str]:
        """Parse IDF file for study metadata"""
        try:
            response = requests.get(idf_url, timeout=60)
            if response.status_code != 200:
                return {}
            
            idf_data = {}
            lines = response.text.strip().split('\\n')
            
            for line in lines:
                if '\\t' in line:
                    parts = line.split('\\t', 1)
                    if len(parts) >= 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        idf_data[key] = value
            
            return idf_data
            
        except Exception as e:
            self.logger.error(f"IDF parsing failed: {str(e)}")
            return {}
    
    def _parse_sdrf(self, sdrf_url: str) -> tuple[List[Dict], Dict[str, Dict], Dict[str, Dict]]:
        """Parse SDRF file for sample and assay information"""
        try:
            response = requests.get(sdrf_url, timeout=60)
            if response.status_code != 200:
                return [], {}, {}
            
            lines = response.text.strip().split('\\n')
            if len(lines) < 2:
                return [], {}, {}
            
            headers = [h.strip() for h in lines[0].split('\\t')]
            rows = []
            samples = {}
            assays = {}
            
            for line in lines[1:]:
                fields = [f.strip() for f in line.split('\\t')]
                row_data = dict(zip(headers, fields))
                rows.append(row_data)
                
                # Extract sample information
                source_name = row_data.get("Source Name", "")
                if source_name and source_name not in samples:
                    samples[source_name] = {
                        "source_name": source_name,
                        "organism": row_data.get("Characteristics [organism]", ""),
                        "tissue": row_data.get("Characteristics [organism part]", ""),
                        "cell_type": row_data.get("Characteristics [cell type]", ""),
                        "biosample_id": row_data.get("Comment [BioSample_ID]", "")
                    }
                
                # Extract assay information
                assay_name = row_data.get("Assay Name", "")
                if assay_name and assay_name not in assays:
                    assays[assay_name] = {
                        "assay_name": assay_name,
                        "source_name": source_name,
                        "technology_type": row_data.get("Technology Type", ""),
                        "array_design_ref": row_data.get("Array Design REF", "")
                    }
            
            return rows, samples, assays
            
        except Exception as e:
            self.logger.error(f"SDRF parsing failed: {str(e)}")
            return [], {}, {}
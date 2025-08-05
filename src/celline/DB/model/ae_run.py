from dataclasses import dataclass
from typing import Final, Optional, Dict, List
import requests
import json
from celline.DB.dev.model import BaseModel, RunSchema


@dataclass
class AE_Run_Schema(RunSchema):
    """ArrayExpress Run schema with ENA integration"""
    library_strategy: Optional[str] = None
    library_source: Optional[str] = None
    platform: Optional[str] = None
    instrument_model: Optional[str] = None
    read_count: Optional[int] = None
    base_count: Optional[int] = None
    experiment_accession: Optional[str] = None
    sample_accession: Optional[str] = None


class AE_Run(BaseModel[AE_Run_Schema]):
    """ArrayExpress Run model with ENA API integration"""
    
    ENA_API_URL: Final[str] = "https://www.ebi.ac.uk/ena/browser/api"
    ENA_FTP_BASE: Final[str] = "ftp.sra.ebi.ac.uk/vol1"
    ASPERA_BASE: Final[str] = "fasp.sra.ebi.ac.uk:/vol1"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[AE_Run_Schema]:
        return AE_Run_Schema

    @classmethod
    def _validate_run_id(cls, run_id: str) -> bool:
        """Validate ENA run ID format"""
        return run_id.startswith(("ERR", "SRR", "DRR"))

    @classmethod
    def _fetch_run_metadata(cls, run_id: str) -> dict:
        """Fetch run metadata from ENA API with comprehensive error handling"""
        if not cls._validate_run_id(run_id):
            raise ValueError(f"Invalid ENA run ID format: {run_id}")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Try ENA browser API first
                url = f"{cls.ENA_API_URL}/search"
                params = {
                    "query": f"run_accession={run_id}",
                    "result": "read_run",
                    "format": "json",
                    "limit": "1"
                }
                
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if isinstance(data, list) and len(data) > 0:
                            run_data = data[0]
                            if run_data.get("run_accession") == run_id:
                                return cls._parse_ena_run_data(run_data)
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid ENA JSON for {run_id} (attempt {attempt + 1}): {e}")

                elif response.status_code == 404:
                    raise ValueError(f"ENA run {run_id} not found (HTTP 404)")
                elif response.status_code >= 500:
                    print(f"Warning: ENA server error for {run_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching ENA run {run_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        # Fallback to alternative ENA endpoint
        try:
            return cls._fetch_run_via_xml(run_id)
        except Exception as e:
            print(f"Warning: Both JSON and XML ENA APIs failed for {run_id}: {e}")
        
        # Return minimal data structure as last resort
        return {
            "run_accession": run_id,
            "experiment_accession": "",
            "sample_accession": "",
            "study_accession": "",
            "library_strategy": "Unknown",
            "library_source": "Unknown",
            "platform": "Unknown",
            "instrument_model": "Unknown",
            "read_count": 0,
            "base_count": 0,
            "fastq_files": [],
            "sra_files": []
        }

    @classmethod
    def _fetch_run_via_xml(cls, run_id: str) -> dict:
        """Fetch run data via ENA XML API as fallback"""
        try:
            url = f"https://www.ebi.ac.uk/ena/browser/api/xml/{run_id}"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                # Parse XML content (simplified - could use xml.etree.ElementTree for full parsing)
                content = response.text
                
                # Extract basic information using simple string parsing
                metadata = {
                    "run_accession": run_id,
                    "experiment_accession": cls._extract_xml_value(content, "experiment_accession"),
                    "sample_accession": cls._extract_xml_value(content, "sample_accession"),
                    "study_accession": cls._extract_xml_value(content, "study_accession"),
                    "library_strategy": cls._extract_xml_value(content, "library_strategy"),
                    "library_source": cls._extract_xml_value(content, "library_source"),
                    "platform": cls._extract_xml_value(content, "platform"),
                    "instrument_model": cls._extract_xml_value(content, "instrument_model"),
                    "read_count": 0,
                    "base_count": 0,
                    "fastq_files": [],
                    "sra_files": []
                }
                
                return metadata
        except Exception as e:
            print(f"Warning: XML API fallback failed for {run_id}: {e}")
        
        raise Exception(f"All ENA API methods failed for {run_id}")

    @classmethod
    def _extract_xml_value(cls, xml_content: str, field: str) -> str:
        """Simple XML value extraction"""
        try:
            start_tag = f'<{field}>'
            end_tag = f'</{field}>'
            start_idx = xml_content.find(start_tag)
            if start_idx != -1:
                start_idx += len(start_tag)
                end_idx = xml_content.find(end_tag, start_idx)
                if end_idx != -1:
                    return xml_content[start_idx:end_idx].strip()
        except Exception:
            pass
        return ""

    @classmethod
    def _parse_ena_run_data(cls, data: dict) -> dict:
        """Parse ENA API response data"""
        try:
            metadata = {
                "run_accession": data.get("run_accession", ""),
                "experiment_accession": data.get("experiment_accession", ""),
                "sample_accession": data.get("sample_accession", ""),
                "study_accession": data.get("study_accession", ""),
                "library_strategy": data.get("library_strategy", ""),
                "library_source": data.get("library_source", ""),
                "platform": data.get("platform", ""),
                "instrument_model": data.get("instrument_model", ""),
                "read_count": cls._safe_int(data.get("read_count", 0)),
                "base_count": cls._safe_int(data.get("base_count", 0)),
                "fastq_files": [],
                "sra_files": []
            }
            
            # Parse file information
            fastq_ftp = data.get("fastq_ftp", "")
            fastq_aspera = data.get("fastq_aspera", "")
            sra_ftp = data.get("sra_ftp", "")
            
            if fastq_ftp:
                metadata["fastq_files"] = [url.strip() for url in fastq_ftp.split(";") if url.strip()]
            
            if sra_ftp:
                metadata["sra_files"] = [url.strip() for url in sra_ftp.split(";") if url.strip()]
            
            # If no direct FTP links, construct them
            if not metadata["fastq_files"] and not metadata["sra_files"]:
                metadata["fastq_files"] = cls._construct_fastq_urls(metadata["run_accession"])
                metadata["sra_files"] = cls._construct_sra_urls(metadata["run_accession"])
            
            return metadata
            
        except Exception as e:
            print(f"Warning: Failed to parse ENA run data: {e}")
            return {
                "run_accession": data.get("run_accession", ""),
                "experiment_accession": "",
                "sample_accession": "",
                "study_accession": "",
                "library_strategy": "Unknown",
                "library_source": "Unknown", 
                "platform": "Unknown",
                "instrument_model": "Unknown",
                "read_count": 0,
                "base_count": 0,
                "fastq_files": [],
                "sra_files": []
            }

    @classmethod
    def _safe_int(cls, value) -> int:
        """Safely convert value to integer"""
        try:
            return int(value) if value else 0
        except (ValueError, TypeError):
            return 0

    @classmethod
    def _construct_fastq_urls(cls, run_id: str) -> list[str]:
        """Construct FASTQ FTP URLs based on run ID"""
        if not run_id or len(run_id) < 6:
            return []
        
        try:
            # ENA FTP structure: ftp.sra.ebi.ac.uk/vol1/fastq/ERR123/ERR123456/ERR123456_1.fastq.gz
            prefix = run_id[:6]  # ERR123
            base_url = f"ftp://{cls.ENA_FTP_BASE}/fastq/{prefix}/{run_id}"
            
            # Common FASTQ file patterns
            urls = [
                f"{base_url}/{run_id}_1.fastq.gz",
                f"{base_url}/{run_id}_2.fastq.gz",
                f"{base_url}/{run_id}.fastq.gz"
            ]
            
            return urls
        except Exception:
            return []

    @classmethod
    def _construct_sra_urls(cls, run_id: str) -> list[str]:
        """Construct SRA FTP URLs based on run ID"""
        if not run_id or len(run_id) < 6:
            return []
        
        try:
            # ENA SRA structure: ftp.sra.ebi.ac.uk/vol1/sra/ERR123/ERR123456
            prefix = run_id[:6]
            base_url = f"ftp://{cls.ENA_FTP_BASE}/sra/{prefix}"
            
            return [f"{base_url}/{run_id}"]
        except Exception:
            return []

    @classmethod
    def _determine_strategy_from_ena(cls, run_data: dict) -> str:
        """Determine sequencing strategy from ENA metadata"""
        strategy = run_data.get("library_strategy", "").lower()
        
        # Map ENA library strategies to Celline strategies
        strategy_mapping = {
            "rna-seq": "fastq",
            "dna-seq": "fastq", 
            "wgs": "fastq",
            "wes": "fastq",
            "chip-seq": "fastq",
            "atac-seq": "fastq",
            "bisulfite-seq": "fastq",
            "amplicon": "fastq"
        }
        
        return strategy_mapping.get(strategy, "fastq")

    def search(self, acceptable_id: str, force_search=False) -> AE_Run_Schema:
        """Search for ArrayExpress Run by ENA accession ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Fetch run metadata from ENA
        metadata = self._fetch_run_metadata(acceptable_id)
        
        # Determine strategy and build download URLs
        strategy = self._determine_strategy_from_ena(metadata)
        
        # Combine FASTQ and SRA URLs for raw_link
        all_urls = metadata.get("fastq_files", []) + metadata.get("sra_files", [])
        raw_link = ",".join(all_urls) if all_urls else ""
        
        return self.add_schema(
            AE_Run_Schema(
                key=acceptable_id,
                parent=metadata.get("sample_accession"),
                children=None,  # Runs are leaf nodes
                title=f"ArrayExpress Run {acceptable_id}",
                strategy=strategy,
                raw_link=raw_link,
                library_strategy=metadata.get("library_strategy"),
                library_source=metadata.get("library_source"),
                platform=metadata.get("platform"),
                instrument_model=metadata.get("instrument_model"),
                read_count=metadata.get("read_count"),
                base_count=metadata.get("base_count"),
                experiment_accession=metadata.get("experiment_accession"),
                sample_accession=metadata.get("sample_accession")
            )
        )
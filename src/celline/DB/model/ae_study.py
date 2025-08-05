from dataclasses import dataclass
from typing import Final, Optional
import requests
import json
from celline.DB.dev.model import BaseModel, BaseSchema


@dataclass
class AE_Study_Schema(BaseSchema):
    """ArrayExpress Study schema for E-MTAB/E-GEOD/E-MEXP accessions"""
    summary: str
    organism: str
    experiment_type: str
    release_date: str
    submission_date: str
    pubmed_id: Optional[str] = None
    doi: Optional[str] = None


class AE_Study(BaseModel[AE_Study_Schema]):
    """ArrayExpress Study (E-MTAB/E-GEOD/E-MEXP) model with BioStudies API integration"""
    
    BASE_API_URL: Final[str] = "https://www.ebi.ac.uk/biostudies/api/v1"
    BASE_FTP_URL: Final[str] = "https://ftp.ebi.ac.uk/biostudies/arrayexpress"
    LEGACY_FTP_URL: Final[str] = "ftp://ftp.ebi.ac.uk/biostudies/arrayexpress"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[AE_Study_Schema]:
        return AE_Study_Schema

    @classmethod
    def _validate_accession(cls, accession_id: str) -> bool:
        """Validate ArrayExpress accession ID format"""
        valid_prefixes = ["E-MTAB-", "E-GEOD-", "E-MEXP-", "E-TABM-", "E-MAGE-", "E-AFMX-"]
        return any(accession_id.startswith(prefix) for prefix in valid_prefixes)

    @classmethod
    def _fetch_study_metadata(cls, accession_id: str) -> dict:
        """Fetch study metadata from BioStudies API with comprehensive error handling"""
        if not cls._validate_accession(accession_id):
            raise ValueError(f"Invalid ArrayExpress accession format: {accession_id}")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Try BioStudies API first
                url = f"{cls.BASE_API_URL}/studies/{accession_id}"
                response = requests.get(url, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if cls._validate_study_data(data, accession_id):
                            return cls._parse_study_metadata(data)
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for {accession_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    raise ValueError(f"ArrayExpress study {accession_id} not found (HTTP 404)")
                elif response.status_code >= 500:
                    print(f"Warning: BioStudies server error for {accession_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching {accession_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        # Fallback to info endpoint
        try:
            return cls._fetch_study_info(accession_id)
        except Exception as e:
            print(f"Warning: Both main and info API failed for {accession_id}: {e}")
        
        # Return minimal data structure as last resort
        return {
            "accession": accession_id,
            "title": f"ArrayExpress Study {accession_id}",
            "description": "Metadata unavailable - API failed", 
            "organism": "Unknown",
            "experiment_type": "Unknown",
            "release_date": "",
            "submission_date": "",
            "samples": [],
            "pubmed_id": None,
            "doi": None
        }

    @classmethod
    def _fetch_study_info(cls, accession_id: str) -> dict:
        """Fetch basic study info as fallback"""
        try:
            url = f"{cls.BASE_API_URL}/studies/{accession_id}/info"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "accession": accession_id,
                    "title": data.get("title", f"ArrayExpress Study {accession_id}"),
                    "description": data.get("description", "Description unavailable"),
                    "organism": "Unknown",
                    "experiment_type": "Unknown", 
                    "release_date": data.get("releaseDate", ""),
                    "submission_date": data.get("submissionDate", ""),
                    "samples": [],
                    "pubmed_id": None,
                    "doi": None,
                    "ftp_link": data.get("ftpLink", "")
                }
        except Exception as e:
            print(f"Warning: Study info fetch failed for {accession_id}: {e}")
        
        raise Exception(f"All API methods failed for {accession_id}")

    @classmethod
    def _validate_study_data(cls, data: dict, accession_id: str) -> bool:
        """Validate study data structure"""
        if not isinstance(data, dict):
            return False
        
        # Check for required fields
        if data.get("accno") != accession_id:
            return False
        
        return True

    @classmethod
    def _parse_study_metadata(cls, data: dict) -> dict:
        """Parse study metadata from BioStudies API response"""
        try:
            # Extract basic information
            metadata = {
                "accession": data.get("accno", ""),
                "title": data.get("title", ""),
                "description": "",
                "organism": "Unknown",
                "experiment_type": "Unknown",
                "release_date": data.get("releaseDate", ""),
                "submission_date": data.get("submissionDate", ""),
                "samples": [],
                "pubmed_id": None,
                "doi": None
            }
            
            # Parse attributes for additional metadata
            attributes = data.get("attributes", [])
            for attr in attributes:
                name = attr.get("name", "").lower()
                value = attr.get("value", "")
                
                if name in ["description", "title"]:
                    metadata["description"] = value
                elif name in ["organism", "species"]:
                    metadata["organism"] = value
                elif name in ["experiment_type", "assay_type", "technology_type"]:
                    metadata["experiment_type"] = value
                elif name in ["pubmed_id", "pubmedid"]:
                    metadata["pubmed_id"] = value
                elif name in ["doi"]:
                    metadata["doi"] = value
            
            # Parse sections for samples and links
            sections = data.get("section", [])
            if not isinstance(sections, list):
                sections = [sections]
            
            sample_ids = []
            for section in sections:
                section_type = section.get("type", "")
                if section_type in ["Study", "Samples"]:
                    # Look for subsections with samples
                    subsections = section.get("subsections", [])
                    for subsection in subsections:
                        links = subsection.get("links", [])
                        for link in links:
                            href = link.get("href", "")
                            if href.startswith("SAMEA") or href.startswith("SAME"):
                                sample_ids.append(href)
            
            metadata["samples"] = list(set(sample_ids))  # Remove duplicates
            return metadata
            
        except Exception as e:
            print(f"Warning: Failed to parse study metadata: {e}")
            # Return basic structure with available data
            return {
                "accession": data.get("accno", ""),
                "title": data.get("title", ""),
                "description": "Parsing failed",
                "organism": "Unknown",
                "experiment_type": "Unknown", 
                "release_date": data.get("releaseDate", ""),
                "submission_date": data.get("submissionDate", ""),
                "samples": [],
                "pubmed_id": None,
                "doi": None
            }

    @classmethod
    def _fetch_study_samples_from_sdrf(cls, accession_id: str) -> list[str]:
        """Fetch sample IDs from SDRF file as alternative method"""
        try:
            # Construct SDRF URL based on accession pattern
            ftp_path = cls._construct_ftp_path(accession_id)
            sdrf_url = f"{cls.BASE_FTP_URL}/{ftp_path}/{accession_id}.sdrf.txt"
            
            response = requests.get(sdrf_url, timeout=30)
            if response.status_code == 200:
                # Parse SDRF to extract sample information
                lines = response.text.strip().split('\n')
                if len(lines) > 1:
                    header = lines[0].split('\t')
                    sample_cols = [i for i, col in enumerate(header) if 'source name' in col.lower() or 'sample' in col.lower()]
                    
                    samples = set()
                    for line in lines[1:]:
                        fields = line.split('\t')
                        for col_idx in sample_cols:
                            if col_idx < len(fields) and fields[col_idx]:
                                samples.add(fields[col_idx])
                    
                    return list(samples)
        except Exception as e:
            print(f"Warning: SDRF parsing failed for {accession_id}: {e}")
        
        return []

    @classmethod
    def _construct_ftp_path(cls, accession_id: str) -> str:
        """Construct FTP path based on accession ID"""
        # ArrayExpress FTP structure: fire/E-MTAB/638/E-MTAB-12638/
        if accession_id.startswith("E-MTAB-"):
            number = accession_id.split("-")[-1]
            # Group by thousands: E-MTAB-12638 -> 12638 -> 638 (last 3 digits)
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-MTAB/{group}/{accession_id}"
        elif accession_id.startswith("E-GEOD-"):
            number = accession_id.split("-")[-1]
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-GEOD/{group}/{accession_id}"
        else:
            # Generic pattern for other prefixes
            prefix = accession_id.split("-")[1] if "-" in accession_id else "UNKNOWN"
            number = accession_id.split("-")[-1] if "-" in accession_id else "000"
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-{prefix}/{group}/{accession_id}"

    def search(self, acceptable_id: str, force_search=False) -> AE_Study_Schema:
        """Search for ArrayExpress Study by accession ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Fetch study metadata
        metadata = self._fetch_study_metadata(acceptable_id)
        
        # Try to get samples from SDRF if not available from API
        if not metadata.get("samples"):
            metadata["samples"] = self._fetch_study_samples_from_sdrf(acceptable_id)
        
        return self.add_schema(
            AE_Study_Schema(
                key=acceptable_id,
                parent=None,  # Studies are top-level
                children=",".join(metadata["samples"]) if metadata["samples"] else None,
                title=metadata.get("title", f"ArrayExpress Study {acceptable_id}"),
                summary=metadata.get("description", "Summary unavailable"),
                organism=metadata.get("organism", "Unknown"),
                experiment_type=metadata.get("experiment_type", "Unknown"),
                release_date=metadata.get("release_date", ""),
                submission_date=metadata.get("submission_date", ""),
                pubmed_id=metadata.get("pubmed_id"),
                doi=metadata.get("doi")
            )
        )
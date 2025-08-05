from dataclasses import dataclass
from typing import Final, Optional, Dict, List
import requests
import json
from celline.DB.dev.model import BaseModel, SampleSchema


@dataclass
class AE_Sample_Schema(SampleSchema):
    """ArrayExpress Sample schema with BioSamples integration"""
    organism: Optional[str] = None
    tissue: Optional[str] = None
    cell_type: Optional[str] = None
    disease: Optional[str] = None
    treatment: Optional[str] = None
    assay_ids: Optional[str] = None  # Comma-separated assay names


class AE_Sample(BaseModel[AE_Sample_Schema]):
    """ArrayExpress Sample model with BioSamples and SDRF integration"""
    
    BIOSAMPLES_API_URL: Final[str] = "https://www.ebi.ac.uk/biosamples/samples"
    BASE_FTP_URL: Final[str] = "https://ftp.ebi.ac.uk/biostudies/arrayexpress"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[AE_Sample_Schema]:
        return AE_Sample_Schema

    @classmethod
    def _validate_sample_id(cls, sample_id: str) -> bool:
        """Validate sample ID format (BioSamples or ArrayExpress format)"""
        return (sample_id.startswith(("SAMEA", "SAMN", "SAMD")) or 
                sample_id.startswith("source_") or 
                len(sample_id) > 0)  # Accept various sample naming conventions

    @classmethod
    def _fetch_biosamples_metadata(cls, sample_id: str) -> dict:
        """Fetch metadata from BioSamples API"""
        if not sample_id.startswith(("SAMEA", "SAMN", "SAMD")):
            return {}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{cls.BIOSAMPLES_API_URL}/{sample_id}"
                response = requests.get(url, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        return cls._parse_biosamples_data(data)
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid BioSamples JSON for {sample_id} (attempt {attempt + 1}): {e}")

                elif response.status_code == 404:
                    print(f"Warning: BioSamples entry {sample_id} not found")
                    return {}
                elif response.status_code >= 500:
                    print(f"Warning: BioSamples server error for {sample_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching BioSamples {sample_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        return {}

    @classmethod
    def _parse_biosamples_data(cls, data: dict) -> dict:
        """Parse BioSamples API response"""
        try:
            metadata = {
                "accession": data.get("accession", ""),
                "title": data.get("name", ""),
                "description": data.get("description", ""),
                "organism": "",
                "tissue": "",
                "cell_type": "",
                "disease": "",
                "treatment": "",
                "submission_date": data.get("submitted", ""),
                "update_date": data.get("updated", ""),
                "external_references": []
            }
            
            # Parse characteristics
            characteristics = data.get("characteristics", {})
            for key, values in characteristics.items():
                key_lower = key.lower()
                if isinstance(values, list) and values:
                    value = values[0].get("text", "") if isinstance(values[0], dict) else str(values[0])
                else:
                    value = str(values) if values else ""
                
                if key_lower in ["organism", "species"]:
                    metadata["organism"] = value
                elif key_lower in ["tissue", "organ", "tissue_type"]:
                    metadata["tissue"] = value
                elif key_lower in ["cell_type", "cell type", "celltype"]:
                    metadata["cell_type"] = value
                elif key_lower in ["disease", "disease_state", "phenotype"]:
                    metadata["disease"] = value
                elif key_lower in ["treatment", "compound", "drug"]:
                    metadata["treatment"] = value
            
            # Parse external references
            external_refs = data.get("externalReferences", [])
            for ref in external_refs:
                if ref.get("url"):
                    metadata["external_references"].append(ref["url"])
            
            return metadata
            
        except Exception as e:
            print(f"Warning: Failed to parse BioSamples data: {e}")
            return {
                "accession": data.get("accession", ""),
                "title": data.get("name", ""),
                "description": "Parsing failed",
                "organism": "",
                "tissue": "",
                "cell_type": "",
                "disease": "",
                "treatment": ""
            }

    @classmethod
    def _fetch_sample_from_sdrf(cls, study_id: str, sample_id: str) -> dict:
        """Fetch sample metadata from SDRF file"""
        try:
            ftp_path = cls._construct_ftp_path(study_id)
            sdrf_url = f"{cls.BASE_FTP_URL}/{ftp_path}/{study_id}.sdrf.txt"
            
            response = requests.get(sdrf_url, timeout=30)
            if response.status_code == 200:
                return cls._parse_sdrf_for_sample(response.text, sample_id)
        except Exception as e:
            print(f"Warning: SDRF fetch failed for {study_id}/{sample_id}: {e}")
        
        return {}

    @classmethod
    def _parse_sdrf_for_sample(cls, sdrf_content: str, sample_id: str) -> dict:
        """Parse SDRF content to extract sample metadata"""
        try:
            lines = sdrf_content.strip().split('\n')
            if len(lines) < 2:
                return {}
            
            headers = [h.strip().lower() for h in lines[0].split('\t')]
            
            # Find relevant columns
            column_mapping = {
                'source_name': ['source name', 'source_name'],
                'sample_name': ['sample name', 'sample_name'],
                'organism': ['organism', 'species', 'organism_part'],
                'tissue': ['organism part', 'tissue', 'cell_type'],
                'description': ['description', 'comment', 'characteristics'],
                'assay_name': ['assay name', 'assay_name'],
                'biosample': ['comment[biosample_id]', 'biosample_id', 'biosample']
            }
            
            # Map column names to indices
            col_indices = {}
            for field, possible_names in column_mapping.items():
                for possible_name in possible_names:
                    if possible_name in headers:
                        col_indices[field] = headers.index(possible_name)
                        break
            
            # Find the sample row
            sample_data = {}
            assay_names = []
            
            for line in lines[1:]:
                fields = [f.strip() for f in line.split('\t')]
                
                # Check if this row matches our sample
                sample_match = False
                if 'source_name' in col_indices and col_indices['source_name'] < len(fields):
                    if fields[col_indices['source_name']] == sample_id:
                        sample_match = True
                elif 'sample_name' in col_indices and col_indices['sample_name'] < len(fields):
                    if fields[col_indices['sample_name']] == sample_id:
                        sample_match = True
                
                if sample_match:
                    # Extract metadata
                    for field, col_idx in col_indices.items():
                        if col_idx < len(fields) and fields[col_idx]:
                            if field == 'assay_name':
                                assay_names.append(fields[col_idx])
                            else:
                                sample_data[field] = fields[col_idx]
            
            if sample_data:
                return {
                    "accession": sample_id,
                    "title": sample_data.get('sample_name', sample_id),
                    "description": sample_data.get('description', ''),
                    "organism": sample_data.get('organism', ''),
                    "tissue": sample_data.get('tissue', ''),
                    "biosample_id": sample_data.get('biosample', ''),
                    "assay_names": assay_names,
                    "parent_study": ""  # Will be set by caller
                }
            
            return {}
            
        except Exception as e:
            print(f"Warning: SDRF parsing failed for sample {sample_id}: {e}")
            return {}

    @classmethod
    def _construct_ftp_path(cls, study_id: str) -> str:
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

    @classmethod
    def _get_runs_from_ena(cls, sample_id: str) -> list[str]:
        """Get ENA run IDs associated with the sample"""
        try:
            # Try ENA browser API
            url = f"https://www.ebi.ac.uk/ena/browser/api/search"
            params = {
                "query": f"sample_accession={sample_id}",
                "result": "read_run",
                "format": "json",
                "limit": "1000"
            }
            
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return [run.get("run_accession", "") for run in data if run.get("run_accession")]
        except Exception as e:
            print(f"Warning: ENA run lookup failed for {sample_id}: {e}")
        
        return []

    def search(self, acceptable_id: str, force_search=False, parent_study: str = None) -> AE_Sample_Schema:
        """Search for ArrayExpress Sample by ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Initialize metadata
        metadata = {
            "title": acceptable_id,
            "description": "",
            "organism": "",
            "tissue": "",
            "cell_type": "", 
            "disease": "",
            "treatment": "",
            "assay_names": [],
            "biosample_id": "",
            "runs": []
        }
        
        # Try BioSamples API if it looks like a BioSamples ID
        biosamples_data = self._fetch_biosamples_metadata(acceptable_id)
        if biosamples_data:
            metadata.update({
                "title": biosamples_data.get("title", acceptable_id),
                "description": biosamples_data.get("description", ""),
                "organism": biosamples_data.get("organism", ""),
                "tissue": biosamples_data.get("tissue", ""),
                "cell_type": biosamples_data.get("cell_type", ""),
                "disease": biosamples_data.get("disease", ""),
                "treatment": biosamples_data.get("treatment", "")
            })
        
        # Try SDRF parsing if parent study is provided
        if parent_study:
            sdrf_data = self._fetch_sample_from_sdrf(parent_study, acceptable_id)
            if sdrf_data:
                # Merge SDRF data, prioritizing non-empty values
                for key, value in sdrf_data.items():
                    if value and (not metadata.get(key) or key in ["assay_names"]):
                        if key == "assay_names":
                            metadata[key] = value
                        else:
                            metadata[key] = value
                
                # Use BioSample ID from SDRF if available
                if sdrf_data.get("biosample_id"):
                    biosample_metadata = self._fetch_biosamples_metadata(sdrf_data["biosample_id"])
                    if biosample_metadata:
                        for key, value in biosample_metadata.items():
                            if value and not metadata.get(key):
                                metadata[key] = value
        
        # Get associated runs from ENA
        runs = []
        if metadata.get("biosample_id"):
            runs = self._get_runs_from_ena(metadata["biosample_id"])
        if not runs and acceptable_id.startswith(("SAMEA", "SAMN")):
            runs = self._get_runs_from_ena(acceptable_id)
        
        return self.add_schema(
            AE_Sample_Schema(
                key=acceptable_id,
                parent=parent_study,
                children=",".join(runs) if runs else None,
                title=metadata.get("title", acceptable_id),
                summary=metadata.get("description", "Summary unavailable"),
                species=metadata.get("organism", "Unknown"),
                raw_link="",  # ArrayExpress samples don't have direct raw links
                organism=metadata.get("organism"),
                tissue=metadata.get("tissue"),
                cell_type=metadata.get("cell_type"),
                disease=metadata.get("disease"),
                treatment=metadata.get("treatment"),
                assay_ids=",".join(metadata.get("assay_names", [])) if metadata.get("assay_names") else None
            )
        )
"""
Export metadata report functionality for Celline.
"""

import argparse
import os
from datetime import datetime
from typing import Optional, Dict, List
from rich.console import Console

from celline.functions._base import CellineFunction
from celline.sample.sample_handler import SampleResolver
from celline.DB.dev.handler import HandleResolver

console = Console()


class ExportMetaReport(CellineFunction):
    """Generate HTML metadata report from samples.toml."""
    
    def __init__(self, output_file: str = "metadata_report.html", **kwargs) -> None:
        super().__init__(**kwargs)
        self.output_file = output_file
    
    def register(self) -> str:
        return "export_metareport"
    
    def call(self, project):
        """Generate metadata report."""
        console.print("[cyan]🔍 Collecting sample metadata...[/cyan]")
        
        # Read samples using SampleResolver
        try:
            SampleResolver.refresh()  # Ensure fresh data
            samples_info = SampleResolver.samples
        except Exception as e:
            console.print(f"[red]Error reading samples: {e}[/red]")
            return project
        
        if not samples_info:
            console.print("[yellow]No samples found in samples.toml[/yellow]")
            return project
        
        console.print(f"Found {len(samples_info)} samples to process")
        
        # Collect metadata for each sample
        sample_metadata = []
        
        for sample_id, sample_info in samples_info.items():
            console.print(f"[dim]Processing {sample_id}...[/dim]")
            try:
                # Get metadata from the sample schema (already cached)
                metadata = sample_info.schema
                
                # Determine the data source based on sample ID pattern
                data_source = self._identify_data_source(sample_id)
                
                console.print(f"[green]✓ Retrieved metadata for {sample_id} from {data_source}[/green]")
                
                sample_metadata.append({
                    'id': sample_id,
                    'description': self._get_sample_description(sample_id),
                    'metadata': metadata,
                    'data_source': data_source,
                    'error': None
                })
            except Exception as e:
                console.print(f"[red]✗ Failed to retrieve {sample_id}: {str(e)}[/red]")
                sample_metadata.append({
                    'id': sample_id,
                    'description': self._get_sample_description(sample_id),
                    'metadata': None,
                    'data_source': 'Unknown',
                    'error': str(e)
                })
        
        # Enrich sample metadata with additional details
        console.print("[cyan]🔬 Enriching metadata with experimental details...[/cyan]")
        enriched_metadata = self._enrich_sample_metadata(sample_metadata)
        
        # Generate HTML report
        console.print(f"[cyan]📝 Generating HTML report: {self.output_file}[/cyan]")
        self._generate_html_report(enriched_metadata, project)
        
        return project
    
    def _identify_data_source(self, sample_id: str) -> str:
        """Identify the data source based on sample ID pattern."""
        if sample_id.startswith('GSM') or sample_id.startswith('GSE'):
            return 'GEO (Gene Expression Omnibus)'
        elif sample_id.startswith('SRR') or sample_id.startswith('SRX'):
            return 'SRA (Sequence Read Archive)'
        elif sample_id.startswith('CRA') or sample_id.startswith('CRR'):
            return 'CNCB (China National Center for Bioinformation)'
        else:
            return 'Public Database'
    
    def _get_sample_description(self, sample_id: str) -> str:
        """Get sample description from samples.toml."""
        import toml
        from celline.config import Config
        
        samples_path = f"{Config.PROJ_ROOT}/samples.toml"
        try:
            with open(samples_path, 'r', encoding='utf-8') as f:
                samples = toml.load(f)
            return samples.get(sample_id, sample_id)
        except Exception:
            return sample_id
    
    def _enrich_sample_metadata(self, sample_metadata: List[Dict]) -> List[Dict]:
        """Enrich sample metadata with additional SRA and experimental details."""
        enriched_metadata = []
        
        for sample in sample_metadata:
            if sample['error'] is None:
                try:
                    # Get additional experimental details from GEO
                    enhanced_data = self._get_experimental_details(sample['id'])
                    if enhanced_data:
                        # Add experimental details to metadata
                        for key, value in enhanced_data.items():
                            # Always set the enriched data, as it's more detailed than basic metadata
                            setattr(sample['metadata'], key, value)
                    
                    # Get SRA strategy information
                    sra_info = self._get_sra_strategy_info(sample['metadata'])
                    if sra_info:
                        for key, value in sra_info.items():
                            setattr(sample['metadata'], key, value)
                            
                except Exception as e:
                    console.print(f"[yellow]Could not enrich metadata for {sample['id']}: {e}[/yellow]")
            
            enriched_metadata.append(sample)
        
        return enriched_metadata
    
    def _get_experimental_details(self, sample_id: str) -> Optional[Dict]:
        """Get additional experimental details from GEO API."""
        try:
            import requests
            import xml.etree.ElementTree as ET
            
            if not sample_id.startswith('GSM'):
                return None
            
            # Use the correct GEO API endpoint
            url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}&targ=gsm&form=xml&view=full"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                # Parse XML with namespace handling
                root = ET.fromstring(response.content)
                details = {}
                
                # Define namespace for GEO XML
                ns = {'geo': 'http://www.ncbi.nlm.nih.gov/geo/info/MINiML'}
                
                # Extract title
                title_elem = root.find('.//geo:Sample/geo:Title', ns)
                if title_elem is not None and title_elem.text:
                    details['title'] = title_elem.text.strip()
                
                # Extract description/summary
                desc_elem = root.find('.//geo:Sample/geo:Description', ns)
                if desc_elem is not None and desc_elem.text:
                    details['description'] = desc_elem.text.strip()
                
                # Extract protocol information
                for protocol_elem in root.findall('.//geo:Sample/geo:Protocol', ns):
                    if protocol_elem.text:
                        protocol_text = protocol_elem.text.strip()
                        if len(protocol_text) > 50:  # Only use substantial protocol descriptions
                            details['experimental_protocol'] = protocol_text
                            break
                
                # Extract characteristics (organism, tissue, etc.)
                characteristics = {}
                for char_elem in root.findall('.//geo:Sample/geo:Characteristics', ns):
                    tag_attr = char_elem.get('tag')
                    if tag_attr and char_elem.text:
                        characteristics[tag_attr] = char_elem.text.strip()
                
                if characteristics:
                    details['characteristics'] = characteristics
                
                # Extract supplementary file links (raw data links)
                supp_files = []
                for supp_elem in root.findall('.//geo:Sample/geo:Supplementary-Data', ns):
                    if supp_elem.text:
                        supp_files.append(supp_elem.text.strip())
                
                if supp_files:
                    details['supplementary_files'] = supp_files
                
                return details if details else None
                
        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve experimental details for {sample_id}: {e}[/dim yellow]")
            return None
    
    def _get_sra_strategy_info(self, metadata) -> Optional[Dict]:
        """Get SRA strategy and library information."""
        try:
            if not hasattr(metadata, 'key') or not metadata.key:
                return None
            
            import requests
            import xml.etree.ElementTree as ET
            
            # First try to get SRX from the sample metadata
            srx_id = None
            if hasattr(metadata, 'srx_id') and metadata.srx_id:
                srx_id = metadata.srx_id
            elif hasattr(metadata, 'children') and metadata.children:
                # Sometimes SRX is in children
                children = str(metadata.children)
                if 'SRX' in children:
                    import re
                    srx_match = re.search(r'SRX\d+', children)
                    if srx_match:
                        srx_id = srx_match.group()
            
            if not srx_id:
                return None
            
            # Query SRA API for strategy information
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id={srx_id}&rettype=xml"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                strategy_info = {}
                
                # Extract library strategy, source, and layout
                for elem in root.iter():
                    if elem.tag == 'LIBRARY_STRATEGY':
                        strategy_info['strategy'] = elem.text
                    elif elem.tag == 'LIBRARY_SOURCE':
                        strategy_info['library_source'] = elem.text
                    elif elem.tag == 'LIBRARY_LAYOUT':
                        # Get the layout type (SINGLE or PAIRED)
                        for child in elem:
                            strategy_info['library_layout'] = child.tag
                            break
                    elif elem.tag == 'PLATFORM':
                        # Get platform information
                        for platform_child in elem:
                            if platform_child.tag in ['ILLUMINA', 'OXFORD_NANOPORE', 'PACBIO_SMRT']:
                                strategy_info['platform'] = platform_child.tag
                                for instrument in platform_child:
                                    if instrument.tag == 'INSTRUMENT_MODEL':
                                        strategy_info['instrument'] = instrument.text
                                        break
                                break
                
                return strategy_info if strategy_info else None
                
        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve SRA strategy info: {e}[/dim yellow]")
            return None
    
    def _generate_strategy_info_html(self, metadata) -> str:
        """Generate HTML for sequencing strategy information."""
        strategy_html = ""
        
        # Check for strategy information
        strategy_attrs = ['strategy', 'library_source', 'library_layout', 'platform', 'instrument']
        strategy_data = {}
        
        for attr in strategy_attrs:
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    strategy_data[attr] = value
        
        if strategy_data:
            items_html = ""
            for attr, value in strategy_data.items():
                attr_label = attr.replace('_', ' ').title()
                items_html += f'''
                <div class="metadata-item">
                    <span class="metadata-label">{attr_label}:</span>
                    <span class="metadata-value">{value}</span>
                </div>'''
            
            # Determine file format based on strategy
            file_format = "Unknown"
            if 'strategy' in strategy_data:
                if strategy_data['strategy'] in ['RNA-Seq', 'ChIP-Seq', 'ATAC-seq']:
                    file_format = "FASTQ"
                elif strategy_data['strategy'] in ['WGS', 'WXS']:
                    file_format = "FASTQ (possibly BAM)"
            
            items_html += f'''
            <div class="metadata-item">
                <span class="metadata-label">Expected Format:</span>
                <span class="metadata-value">{file_format}</span>
            </div>'''
            
            strategy_html = f'''
            <div class="strategy-info">
                <h4>🧬 Sequencing Strategy Information</h4>
                {items_html}
            </div>'''
        
        return strategy_html
    
    def _generate_species_chart_data(self, sample_metadata: List[Dict]) -> tuple:
        """Generate species distribution data for pie chart."""
        species_count = {}
        
        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                species = getattr(sample['metadata'], 'species', 'Unknown')
                if species and species != 'Not specified':
                    species_count[species] = species_count.get(species, 0) + 1
                else:
                    species_count['Unknown'] = species_count.get('Unknown', 0) + 1
        
        if not species_count:
            return [], []
        
        species_labels = list(species_count.keys())
        species_values = list(species_count.values())
        
        return species_labels, species_values
    
    def _generate_species_chart_html(self, species_labels: List[str], species_values: List[int]) -> str:
        """Generate HTML for species pie chart."""
        if not species_labels or not species_values:
            return ""
        
        # Generate colors for the pie chart
        colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', 
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
            '#4BC0C0', '#FF6384', '#36A2EB', '#FFCE56'
        ]
        
        # Prepare data for Chart.js
        labels_json = str(species_labels).replace("'", '"')
        values_json = str(species_values)
        colors_json = str(colors[:len(species_labels)]).replace("'", '"')
        
        chart_html = f'''
        <div class="chart-container">
            <h2>🧬 Species Distribution</h2>
            <div class="chart-canvas">
                <canvas id="speciesChart" width="400" height="400"></canvas>
            </div>
        </div>
        
        <script>
        document.addEventListener('DOMContentLoaded', function() {{
            const ctx = document.getElementById('speciesChart').getContext('2d');
            const speciesChart = new Chart(ctx, {{
                type: 'pie',
                data: {{
                    labels: {labels_json},
                    datasets: [{{
                        data: {values_json},
                        backgroundColor: {colors_json},
                        borderColor: '#ffffff',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 20,
                                usePointStyle: true,
                                font: {{
                                    size: 12
                                }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = Math.round((value / total) * 100);
                                    return label + ': ' + value + ' samples (' + percentage + '%)';
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }});
        </script>
        '''
        
        return chart_html
    
    def _generate_html_report(self, sample_metadata: List[Dict], project):
        """Generate HTML report."""
        html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Celline Metadata Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }}
        .header {{
            border-bottom: 3px solid #2c3e50;
            padding-bottom: 20px;
            margin-bottom: 30px;
            display: flex;
            align-items: center;
            gap: 20px;
        }}
        .header-icon {{
            height: 2.5em;
            width: auto;
            object-fit: contain;
        }}
        .header-text {{
            flex: 1;
        }}
        h1 {{
            color: #2c3e50;
            margin: 0;
            font-size: 2.5em;
        }}
        .subtitle {{
            color: #7f8c8d;
            font-size: 1.1em;
            margin-top: 5px;
        }}
        .summary {{
            background-color: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }}
        .summary-item {{
            text-align: center;
        }}
        .summary-number {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}
        .summary-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .sample {{
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-bottom: 25px;
            overflow: hidden;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .sample-header {{
            background-color: #3498db;
            color: white;
            padding: 15px 20px;
            font-weight: bold;
            font-size: 1.2em;
        }}
        .sample-header.error {{
            background-color: #e74c3c;
        }}
        .sample-content {{
            padding: 20px;
        }}
        .metadata-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }}
        .metadata-section {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }}
        .metadata-section h3 {{
            margin-top: 0;
            color: #2c3e50;
            font-size: 1.1em;
        }}
        .metadata-item {{
            margin-bottom: 10px;
        }}
        .metadata-label {{
            font-weight: bold;
            color: #34495e;
            display: inline-block;
            min-width: 100px;
        }}
        .metadata-value {{
            color: #555;
            word-break: break-word;
        }}
        .error-message {{
            background-color: #fdf2f2;
            color: #e74c3c;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #e74c3c;
        }}
        .description {{
            background-color: #f0f9ff;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
            margin-bottom: 20px;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            background-color: #e8f4fd;
            color: #2980b9;
            border-radius: 12px;
            font-size: 0.85em;
            margin-right: 5px;
        }}
        .data-source-badge {{
            background-color: #e8f4fd;
            color: #2980b9;
            font-weight: bold;
            font-size: 0.8em;
        }}
        .db-link {{
            color: #2980b9;
            text-decoration: none;
            font-weight: bold;
        }}
        .db-link:hover {{
            text-decoration: underline;
        }}
        .chart-container {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .chart-canvas {{
            max-width: 400px;
            margin: 0 auto;
        }}
        .strategy-info {{
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 5px;
        }}
        .strategy-info h4 {{
            margin: 0 0 10px 0;
            color: #856404;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            {celline_icon_html}
            <div class="header-text">
                <h1>Celline Metadata Report</h1>
                <div class="subtitle">Generated on {timestamp} • Data retrieved from public genomics databases</div>
            </div>
        </div>
        
        <div class="summary">
            <div class="summary-item">
                <div class="summary-number">{total_samples}</div>
                <div class="summary-label">Total Samples</div>
            </div>
            <div class="summary-item">
                <div class="summary-number">{successful_samples}</div>
                <div class="summary-label">Successfully Processed</div>
            </div>
            <div class="summary-item">
                <div class="summary-number">{failed_samples}</div>
                <div class="summary-label">Failed</div>
            </div>
        </div>
        
        {species_chart_html}
        
        {samples_html}
        
        <div class="footer">
            Generated by Celline Export MetaReport • Data retrieved from public genomics databases • Project: {project_path}
        </div>
    </div>
</body>
</html>
"""
        
        # Count samples
        total_samples = len(sample_metadata)
        successful_samples = sum(1 for s in sample_metadata if s['error'] is None)
        failed_samples = total_samples - successful_samples
        
        # Generate species chart data
        species_labels, species_values = self._generate_species_chart_data(sample_metadata)
        species_chart_html = self._generate_species_chart_html(species_labels, species_values)
        
        # Get embedded icon
        celline_icon_data = self._get_embedded_icon()
        celline_icon_html = f'<img src="{celline_icon_data}" alt="Celline Logo" class="header-icon">' if celline_icon_data else ''
        
        # Generate samples HTML
        samples_html = ""
        for sample in sample_metadata:
            if sample['error']:
                samples_html += self._generate_error_sample_html(sample)
            else:
                samples_html += self._generate_successful_sample_html(sample)
        
        # Fill template
        html_content = html_template.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_samples=total_samples,
            successful_samples=successful_samples,
            failed_samples=failed_samples,
            celline_icon_html=celline_icon_html,
            species_chart_html=species_chart_html,
            samples_html=samples_html,
            project_path=getattr(project, 'PROJ_PATH', 'Unknown')
        )
        
        # Write HTML file
        output_path = os.path.join(getattr(project, 'PROJ_PATH', '.'), self.output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _generate_successful_sample_html(self, sample: Dict) -> str:
        """Generate HTML for a successfully processed sample."""
        metadata = sample['metadata']
        data_source = sample['data_source']
        
        # Generate appropriate links based on data source
        sample_link = self._generate_sample_link(metadata.key, data_source)
        parent_link = self._generate_sample_link(metadata.parent, data_source) if metadata.parent else metadata.parent
        
        # Get additional metadata if available
        additional_info = self._extract_additional_metadata(metadata)
        
        html = f"""
        <div class="sample">
            <div class="sample-header">
                {sample['id']} <span class="badge data-source-badge">{data_source}</span>
            </div>
            <div class="sample-content">
                <div class="description">
                    <strong>Description:</strong> {sample['description']}
                </div>
                
                <div class="metadata-grid">
                    <div class="metadata-section">
                        <h3>📊 Basic Information</h3>
                        <div class="metadata-item">
                            <span class="metadata-label">Sample ID:</span>
                            <span class="metadata-value">{sample_link}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Title:</span>
                            <span class="metadata-value">{metadata.title if metadata.title else 'Not specified'}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Species:</span>
                            <span class="metadata-value">{metadata.species if metadata.species else 'Not specified'}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Parent Project:</span>
                            <span class="metadata-value">{parent_link if parent_link else 'Not available'}</span>
                        </div>
                    </div>
                    
                    <div class="metadata-section">
                        <h3>🔬 Technical Details</h3>
                        {self._generate_technical_details_html(metadata)}
                        <div class="metadata-item">
                            <span class="metadata-label">Child Runs:</span>
                            <span class="metadata-value">{metadata.children if metadata.children else 'Not available'}</span>
                        </div>
                    </div>
                    
                    <div class="metadata-section">
                        <h3>📝 Experimental Summary</h3>
                        <div class="metadata-item">
                            <div class="metadata-value">{self._get_experimental_summary(metadata)}</div>
                        </div>
                    </div>
                    
                    {self._generate_strategy_info_html(metadata)}
                    {self._generate_raw_links_html(metadata, data_source)}
                    {additional_info}
                </div>
            </div>
        </div>
        """
        return html
    
    def _generate_error_sample_html(self, sample: Dict) -> str:
        """Generate HTML for a failed sample."""
        html = f"""
        <div class="sample">
            <div class="sample-header error">
                {sample['id']} <span class="badge" style="background-color: #fdf2f2; color: #e74c3c;">Error</span>
            </div>
            <div class="sample-content">
                <div class="description">
                    <strong>Description:</strong> {sample['description']}
                </div>
                
                <div class="error-message">
                    <strong>Error:</strong> {sample['error']}
                </div>
            </div>
        </div>
        """
        return html
    
    def _generate_sample_link(self, sample_id: str, data_source: str) -> str:
        """Generate appropriate link for sample based on data source."""
        if not sample_id:
            return "Not available"
        
        if 'GEO' in data_source:
            return f'<a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        elif 'SRA' in data_source:
            return f'<a href="https://www.ncbi.nlm.nih.gov/sra/{sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        elif 'CNCB' in data_source:
            return f'<a href="https://bigd.big.ac.cn/gsa/{sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        else:
            return sample_id
    
    def _generate_technical_details_html(self, metadata) -> str:
        """Generate technical details HTML based on available metadata."""
        details_html = ""
        
        # Check for SRX ID (common in SRA data)
        if hasattr(metadata, 'srx_id') and metadata.srx_id:
            details_html += f'''
            <div class="metadata-item">
                <span class="metadata-label">SRX ID:</span>
                <span class="metadata-value">{metadata.srx_id}</span>
            </div>'''
        
        # Check for additional technical attributes
        technical_attrs = ['strategy', 'platform', 'instrument', 'library_source']
        for attr in technical_attrs:
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    attr_label = attr.replace('_', ' ').title()
                    details_html += f'''
                    <div class="metadata-item">
                        <span class="metadata-label">{attr_label}:</span>
                        <span class="metadata-value">{value}</span>
                    </div>'''
        
        return details_html
    
    def _extract_additional_metadata(self, metadata) -> str:
        """Extract additional metadata that might be available."""
        additional_html = ""
        
        # Check for additional attributes that might be present
        additional_attrs = {
            'description': 'Description',
            'submission_date': 'Submission Date',
            'publication_date': 'Publication Date',
            'last_update_date': 'Last Update',
            'contact_name': 'Contact',
            'organization_name': 'Organization'
        }
        
        available_additional = []
        for attr, label in additional_attrs.items():
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    available_additional.append((label, value))
        
        if available_additional:
            items_html = ""
            for label, value in available_additional:
                items_html += f'''
                <div class="metadata-item">
                    <span class="metadata-label">{label}:</span>
                    <span class="metadata-value">{value}</span>
                </div>'''
            
            additional_html = f'''
            <div class="metadata-section">
                <h3>ℹ️ Additional Information</h3>
                {items_html}
            </div>'''
        
        return additional_html
    
    def _generate_raw_links_html(self, metadata, data_source: str = None) -> str:
        """Generate HTML for raw data links with meaningful titles."""
        # First try to get supplementary files from enriched experimental details
        links = []
        
        if hasattr(metadata, 'supplementary_files') and metadata.supplementary_files:
            if isinstance(metadata.supplementary_files, list):
                links = metadata.supplementary_files
            else:
                links = [metadata.supplementary_files]
        elif hasattr(metadata, 'raw_link') and metadata.raw_link:
            # Fallback to raw_link if supplementary_files not available
            links = [link.strip() for link in str(metadata.raw_link).split(',') if link.strip()]
        
        if not links:
            return ""
        
        links_html = ""
        for link in links:  # Show ALL links, not just first 3
            if link.startswith('ftp://') or link.startswith('http'):
                # Use filename as title directly (no processing)
                filename = link.split('/')[-1] if '/' in link else link
                links_html += f'<div class="metadata-item"><a href="{link}" target="_blank" class="db-link">{filename}</a></div>'
            else:
                links_html += f'<div class="metadata-item"><span class="metadata-value">{link}</span></div>'
        
        return f"""
        <div class="metadata-section">
            <h3>💾 Raw Data Links</h3>
            {links_html}
        </div>
        """
    
    def _get_experimental_summary(self, metadata) -> str:
        """Get the best available experimental summary from enriched metadata."""
        # Priority order for summary sources
        summary_sources = [
            ('experimental_protocol', 'Experimental Protocol'),
            ('description', 'Description'),
            ('api_summary', 'API Summary'),
            ('abstract', 'Abstract'),
            ('summary', 'Summary')
        ]
        
        for attr_name, source_type in summary_sources:
            if hasattr(metadata, attr_name):
                value = getattr(metadata, attr_name)
                if value and str(value).strip():
                    summary_text = str(value).strip()
                    # If the summary is very long, truncate it
                    if len(summary_text) > 800:
                        summary_text = summary_text[:800] + "..."
                    return summary_text
        
        # If no good summary found, return a more informative message
        return "No detailed experimental summary available from the data source."
    
    def _get_embedded_icon(self) -> str:
        """Get base64 encoded Celline icon for HTML embedding."""
        try:
            import base64
            
            # Get the icon path relative to this file
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'celline_icon.png')
            
            if os.path.exists(icon_path):
                with open(icon_path, 'rb') as f:
                    icon_data = f.read()
                
                # Encode to base64
                base64_data = base64.b64encode(icon_data).decode('utf-8')
                return f"data:image/png;base64,{base64_data}"
            else:
                console.print(f"[dim yellow]Celline icon not found at {icon_path}[/dim yellow]")
                return ""
                
        except Exception as e:
            console.print(f"[dim yellow]Could not load Celline icon: {e}[/dim yellow]")
            return ""
    
    def cli(self, project, args: Optional[argparse.Namespace] = None):
        """CLI entry point."""
        if args and hasattr(args, 'output'):
            self.output_file = args.output
        return self.call(project)
    
    def get_description(self) -> str:
        return "Generate HTML metadata report from samples.toml sample IDs."
    
    def get_usage_examples(self) -> list[str]:
        return [
            "celline export metareport",
            "celline export metareport --output my_report.html"
        ]
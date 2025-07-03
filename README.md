# Celline - Single Cell RNA-seq Analysis Pipeline

Celline is a comprehensive, interactive pipeline for single-cell RNA sequencing (scRNA-seq) analysis, designed to streamline the workflow from raw data to biological insights. It provides both command-line and web-based interfaces for flexible analysis workflows.

📖 **Detailed Documentation**: [Celline Docs](https://kataoka-k-lab.github.io/CellineDocs/getting-started "Document")

## Features

- **🔄 Automated Data Processing**: From raw FASTQ files to expression matrices
- **✅ Quality Control**: Built-in QC metrics and filtering with Scrublet doublet detection
- **📊 Dimensionality Reduction**: PCA, t-SNE, and UMAP implementations
- **🔍 Clustering Analysis**: Multiple clustering algorithms
- **🧬 Cell Type Prediction**: Automated cell type annotation using scPred
- **⚖️ Batch Effect Correction**: Multiple methods for data integration (Seurat, scVI)
- **🌐 Interactive Visualization**: Web-based interface for data exploration
- **🔧 Flexible Execution**: Support for local multithreading and PBS cluster execution
- **📁 Database Integration**: Built-in support for SRA, GEO, and CNCB data repositories
- **🔬 R Integration**: Seamless R/Seurat integration for advanced analysis

## System Requirements

### Required Dependencies
- **Python**: ≥3.10
- **R**: ≥4.0 with Seurat and other required packages
- **Cell Ranger**: For 10x Genomics data processing
- **SRA Toolkit**: For downloading SRA data (fastq-dump)

### Python Dependencies
All Python dependencies are automatically installed via pip. Key packages include:
- `scanpy` - Single-cell analysis
- `pandas`, `polars` - Data manipulation
- `fastapi`, `uvicorn` - Web API
- `rich` - Enhanced CLI interface
- `pysradb` - SRA database access

## Installation

### Option 1: Install from PyPI
```bash
pip install celline
```

### Option 2: Install from Source
```bash
git clone https://github.com/your-repo/Celline.git
cd Celline
pip install -e .
```

### Option 3: Development Installation
```bash
git clone https://github.com/your-repo/Celline.git
cd Celline
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize Your Project
Start by initializing a new project. This will validate system dependencies and create configuration files:

```bash
celline init
```

This command will:
- Check for required system dependencies (R, Cell Ranger, SRA Toolkit)
- Set up R environment configuration
- Create project configuration files
- Prompt for project name and settings

### 2. Configure Execution Settings (Optional)
Configure execution parameters for your system:

```bash
# Interactive configuration
celline config

# Or set specific options
celline config --system multithreading --nthread 8
celline config --system PBS --pbs-server your-cluster-name
```

### 3. Explore Available Functions
List all available analysis functions:

```bash
celline list
```

Get detailed help for specific functions:

```bash
celline help download
celline help preprocess
```

### 4. Basic Analysis Workflow

#### Download Public Data
```bash
# Download from SRA/GEO
celline run download --accession GSE123456
celline run download --accession SRR123456

# Download from CNCB
celline run download --accession CRA123456
```

#### Data Preprocessing
```bash
# Quality control and preprocessing
celline run preprocess --input raw_data/ --output processed/

# Gene expression counting (10x data)
celline run count --input cellranger_output/ --output counts/
```

#### Create Seurat Objects
```bash
# Create Seurat object for downstream analysis
celline run create_seurat --input counts/ --output seurat_object.rds
```

#### Advanced Analysis
```bash
# Dimensionality reduction
celline run reduce --input seurat_object.rds --methods pca,umap,tsne

# Cell type prediction
celline run predict_celltype --input seurat_object.rds --reference ref_data/

# Batch effect correction
celline run integrate --input multiple_samples/ --method seurat
```

### 5. Interactive Web Interface
Launch the interactive web interface for visual analysis:

```bash
celline interactive
```

This will:
- Start the FastAPI backend server
- Launch the Vue.js frontend
- Open your web browser automatically
- Provide interactive data exploration tools

### 6. API Server Only (for Development)
Start only the API server for testing:

```bash
celline api
```

## Available Functions

| Function | Description | Usage Example |
|----------|-------------|---------------|
| `init` | Initialize project and validate dependencies | `celline init` |
| `download` | Download scRNA-seq data from public repositories | `celline run download --accession GSE123456` |
| `preprocess` | Quality control and preprocessing | `celline run preprocess` |
| `count` | Gene expression quantification | `celline run count` |
| `create_seurat` | Create Seurat objects | `celline run create_seurat` |
| `reduce` | Dimensionality reduction (PCA, UMAP, t-SNE) | `celline run reduce` |
| `integrate` | Batch effect correction and data integration | `celline run integrate` |
| `predict_celltype` | Automated cell type annotation | `celline run predict_celltype` |
| `batch_cor` | Batch correlation analysis | `celline run batch_cor` |
| `interactive` | Launch web interface | `celline interactive` |
| `sync_DB` | Update local databases | `celline run sync_DB` |
| `info` | Show system information | `celline info` |

## Project Structure

When you initialize a project, Celline creates the following structure:

```
your_project/
├── setting.toml          # Project configuration
├── data/                 # Raw and processed data
├── results/              # Analysis results
├── scripts/              # Generated analysis scripts
└── logs/                 # Execution logs
```

## Configuration

Celline uses `setting.toml` files for configuration:

```toml
[project]
name = "my_project"
version = "0.01"

[execution]
system = "multithreading"  # or "PBS"
nthread = 8
pbs_server = "your-cluster"  # for PBS system

[R]
r_path = "/usr/local/bin/R"

[fetch]
wait_time = 4  # seconds between API calls
```

## Advanced Usage

### Running on HPC Clusters
For PBS/Torque clusters:

```bash
celline config --system PBS --pbs-server your-cluster-name
celline run preprocess  # Will submit PBS jobs automatically
```

### Custom Analysis Scripts
Celline generates executable scripts in the `scripts/` directory that can be run independently or modified for custom workflows.

### R Integration
Access Seurat objects and run custom R analysis:

```bash
# R scripts are available in template/hook/R/
# Custom R functions can be added to the pipeline
```

## Troubleshooting

### Common Issues

1. **Missing Dependencies**: Run `celline init` to validate all dependencies
2. **R Package Issues**: Ensure Seurat and required R packages are installed
3. **Memory Issues**: Adjust thread count with `celline config --nthread <number>`
4. **Web Interface Not Loading**: Check that ports 8000 and 3000 are available

### Getting Help

```bash
# General help
celline help

# Function-specific help
celline help <function_name>

# System information
celline info

# List all functions
celline list
```

## Contributing

We welcome contributions! Please see our contributing guidelines for more information.

## Citation

If you use Celline in your research, please cite:

```
[Citation information to be added]
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

- 📖 [Documentation](https://kataoka-k-lab.github.io/CellineDocs/getting-started)
- 🐛 [Issue Tracker](https://github.com/your-repo/Celline/issues)
- 💬 [Discussions](https://github.com/your-repo/Celline/discussions)

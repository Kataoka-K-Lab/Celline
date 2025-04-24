import os
from pathlib import Path
import sys

import scanpy
import scgen
import scipy
import scipy.io as sio
from scvi.data import setup_anndata

h5ad_path: str = sys.argv[1]
output_filepath: str = sys.argv[2]
output_dir = Path(output_filepath).parent.resolve()

adata = scanpy.read_h5ad(h5ad_path)
os.makedirs(f"{output_dir}/cache", exist_ok=True)
setup_anndata(adata, batch_key="project", labels_key="scpred_prediction")
model = scgen.SCGEN(adata)
model.save(f"{output_dir}/cache/model_perturbation_prediction.pt", overwrite=True)
model.train(
    max_epochs=100, batch_size=32, early_stopping=True, early_stopping_patience=25
)
model.save(f"{output_dir}/cache/model_perturbation_prediction.pt", overwrite=True)
corrected_adata = model.batch_removal()
os.makedirs(output_dir, exist_ok=True)
if not scipy.sparse.issparse(corrected_adata.X):
    corrected_adata.X = scipy.sparse.csr_matrix(corrected_adata.X)
    # sio.mmwrite(f"{output_dir}/corrected.mtx", matrix, field="real", precision=3)
# else:
#     sio.mmwrite(
#         f"{output_dir}/corrected.mtx", corrected_adata.X, field="real", precision=3
#     )
if not output_filepath.endswith("h5ad"):
    output_filepath = f"{output_filepath}.h5ad"
corrected_adata.write_h5ad(Path(output_filepath))

import sys

import scanpy as sc
import scrublet as scr
import polars as pl

raw_matrix_path: str = sys.argv[1]
output_path: str = sys.argv[2]

raw_count = sc.read_10x_h5(raw_matrix_path)
raw_count.var_names_make_unique()
# [WARNING]: n_prin_compsはintで指定するが、Feature selectionがうまくいかない場合があるのでNoneに
doublet_scores, predicted_doublets = scr.Scrublet(raw_count.to_df()).scrub_doublets(
    n_prin_comps=None  # type: ignore
)
pl.DataFrame(
    data={
        "cell": raw_count.obs.index.to_list(),
        "doublet_score": doublet_scores,
        "is_doublet": predicted_doublets,
    }
).write_csv(output_path, separator="\t")

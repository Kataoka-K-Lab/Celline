#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=1:%cluster_server/
#PBS -q %cluster_server/
#PBS -N %jobname/
#PBS -j eo
#PBS -m ae
#PBS -e %logpath/

if [ -e "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi
if [ -e "$HOME/.zshrc" ]; then
    zsh "$HOME/.zshrc"
fi
raw_matrix_path="%raw_matrix_path/"
%py_path/ "%exec_root//template/hook/py/preprocess_scrublet.py" $raw_matrix_path %output_doublet_path/
%r_path/ "%exec_root//template/hook/R/FilterGenes.R" $raw_matrix_path %output_qc_path/ %log_path/

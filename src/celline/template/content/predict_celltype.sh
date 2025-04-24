#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=%nthread/:%cluster_server/
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
%r_path/ "%exec_root//celline/template/hook/R/run_scpred.R"\
    "%reference_seurat/"\
    "%reference_celltype/"\
    "%projects/" \
    "%samples/" \
    "%resources_path/" \
    "%data_path/"

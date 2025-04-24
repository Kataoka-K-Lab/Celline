#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=%nthread/:%cluster_server/
#PBS -q %cluster_server/
#PBS -N %jobname/
#PBS -j eo
#PBS -m ae
#PBS -e %logpath/

## Check command ##
if [ -e "$HOME/.bashrc" ]; then
  source "$HOME/.bashrc"
fi
if [ -e "$HOME/.zshrc" ]; then
  zsh "$HOME/.zshrc"
fi
##################
%r_path/ "%exec_root//celline/template/hook/R/create_seurat.R" "%input_h5_path/" "%data_dir_path/" "%proj_name/" "%useqc_matrix/"

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
h5matrix_path="%h5matrix_path/"
%r_path/ "%exec_root//celline/template/hook/R/build_reference.R" %nthread/ "$h5matrix_path" "%celltype_path/" "%dist_dir/"

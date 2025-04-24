#!/bin/bash
#PBS -S /bin/bash
#PBS -l nodes=1:ppn=1:%cluster_server/
#PBS -q %cluster_server/
#PBS -N BatchCorrection
#PBS -j eo
#PBS -m ae
#PBS -e %logpath/

if [ -e "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi
if [ -e "$HOME/.zshrc" ]; then
    zsh "$HOME/.zshrc"
fi
%r_path/ "%exec_root//celline/template/hook/R/mnncorrect.R" "%sample_ids/" "%project_ids/" "%output_dir/" "%logpath_runtime/" "%proj_path/"